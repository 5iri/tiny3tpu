#!/usr/bin/env python3
"""Recompile the exported classifier and resident samples without retraining."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.program import compile_stablehlo, CompileOptions, KC705, KC705_DIRECT
from sidequests.showcase.build_support import compile_firmware, native_reference, sha256


def prepare_headers(artifacts, out, gemm_policy, tpu_transport='mailbox', *, specialize_matmuls=True):
    (out / 'build-manifest.json').unlink(missing_ok=True)
    artifact = artifacts / 'classifier.mlirbc'
    samples = np.load(artifacts / 'samples.npz')['inputs']
    expected = np.load(artifacts / 'expected.npy')
    if samples.shape != (20, 784) or samples.dtype != np.int8 or expected.shape != (20, 10):
        raise ValueError('Classifier shell requires 20 int8 784-pixel samples and 20x10 reference logits')
    options = CompileOptions(target=KC705_DIRECT if tpu_transport == 'direct' else KC705, symbol='classifier', math_mode='freestanding',
                             allow_approximation=True, gemm_policy=gemm_policy,
                             specialize_matmuls=specialize_matmuls)
    report = compile_stablehlo(artifact, out / 'classifier.h', options)
    counts, reference = [], []
    # Compile the native reference once; every resident sample is checked.
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_stablehlo_compiler import Compiled
    from dataclasses import replace
    native = Compiled(artifact, replace(options, symbol='t3p'))
    try:
        for index, sample in enumerate(samples):
            before = native.library.backend_calls()
            status, outputs = native.run(sample[None, :])
            if status:
                raise ValueError(f'Classifier sample {index} returned {status}')
            np.testing.assert_array_equal(outputs[0].ravel().view(np.uint32), expected[index].view(np.uint32))
            counts.append(int(native.library.backend_calls() - before))
            reference.append(outputs[0].ravel())
    finally:
        native.close()
    np.save(out / 'classifier-expected.npy', reference)
    (out / 'digits.h').write_text('static const int8_t digit_inputs[20][784]={' +
                                 ','.join('{' + ','.join(map(str, row)) + '}' for row in samples) + '};\n')
    report['expected_backend_calls'] = counts[0] if len(set(counts)) == 1 else counts
    (out / 'classifier-report.json').write_text(json.dumps(report, indent=2) + '\n')
    # Existing tooling uses this name in classifier artifact directories.
    (out / 'compile-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, default=ROOT / 'build-classifier')
    parser.add_argument('--out', type=Path, default=ROOT / 'build-classifier/board')
    parser.add_argument('--gemm-policy', choices=('auto', 'cpu', 'tpu'), default='auto')
    parser.add_argument('--optimization', choices=('Os', 'O2', 'O3'), default='O2')
    parser.add_argument('--no-specialize-matmuls', action='store_true',
                        help='Use the generic TPU driver for matched firmware comparisons')
    parser.add_argument('--tpu-transport', choices=('mailbox', 'direct'), default='mailbox')
    parser.add_argument('--io-transport', choices=('uart', 'udp'), default='uart', help='UDP requires freshly synthesized Ethernet hardware')
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument('--compile-only', action='store_true', help='Compile firmware only (default)')
    stage.add_argument('--headers-only', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    # Header/reference changes invalidate any earlier firmware association, even if compilation fails.
    (out / 'build-manifest.json').unlink(missing_ok=True)
    report, counts = prepare_headers(args.artifacts, out, args.gemm_policy, args.tpu_transport,
                                    specialize_matmuls=not args.no_specialize_matmuls)
    if args.headers_only:
        print('Prepared classifier headers and verified all 20 samples; no training or firmware build.')
        return
    build = compile_firmware(ROOT / 'sidequests/showcase/classifier_firmware.c', [out], out,
                             args.optimization, args.tpu_transport, args.io_transport)
    build.update(schema_version=1, gemm_policy=args.gemm_policy,
                 specialize_matmuls=not args.no_specialize_matmuls,
                 artifact_dir=str(args.artifacts.resolve()),
                 reference_sha256={'classifier-expected.npy': sha256(out / 'classifier-expected.npy')},
                 modes=[{'mode': index, 'name': 'classifier', 'words': 11,
                         'gemm_policy': args.gemm_policy, 'expected_backend_calls': calls,
                         'placement': report['placement'], 'native_bit_exact': True,
                         'expected_file': 'classifier-expected.npy'}
                        for index, calls in enumerate(counts)],
                 generated_and_input_sha256={str(path.resolve()): sha256(path) for path in
                                             (args.artifacts / 'classifier.mlirbc', args.artifacts / 'samples.npz',
                                              args.artifacts / 'expected.npy', out / 'classifier.h', out / 'digits.h')})
    (out / 'build-manifest.json').write_text(json.dumps(build, indent=2) + '\n')
    print((out / 'size.log').read_text().strip())
    print(json.dumps({'gemm_policy': args.gemm_policy, 'optimization': args.optimization,
                      'backend_calls_per_sample': counts, 'memory': build['memory']}))


if __name__ == '__main__':
    main()
