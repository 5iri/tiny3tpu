#!/usr/bin/env python3
"""Compile showcase firmware and placement metadata; no FPGA route is required."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.program import compile_stablehlo, CompileOptions, KC705, KC705_CORDIC, KC705_DIRECT, KC705_DIRECT_CORDIC
from sidequests.showcase.build_support import compile_firmware, native_reference, sha256, tpu_placement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, default=ROOT / 'build-showcase')
    parser.add_argument('--out', type=Path, default=ROOT / 'build-showcase/board')
    parser.add_argument('--gemm-policy', choices=('auto', 'cpu', 'tpu'), default='auto')
    parser.add_argument('--optimization', choices=('Os', 'O2', 'O3'), default='O2')
    parser.add_argument('--no-specialize-matmuls', action='store_true',
                        help='Use the generic TPU driver for matched firmware comparisons')
    parser.add_argument('--tpu-transport', choices=('mailbox', 'direct'), default='mailbox')
    parser.add_argument('--ram-kib', type=int, choices=(64, 128, 256, 512), default=64, help='On-chip boot RAM budget in KiB')
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument('--compile-only', action='store_true', help='Compile firmware without routing (default)')
    stage.add_argument('--headers-only', action='store_true', help='Only prepare generated headers, as in older builds')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    # Header/reference changes invalidate any earlier firmware association, even if compilation fails.
    (out / 'build-manifest.json').unlink(missing_ok=True)
    records, fixture, sources = [], [], {}
    base_target = KC705_DIRECT if args.tpu_transport == 'direct' else KC705
    cordic_target = KC705_DIRECT_CORDIC if args.tpu_transport == 'direct' else KC705_CORDIC
    for mode, name, symbol, target in [(0, 'quantized_mlp', 'mlp', base_target),
                                      (1, 'attention_block', 'attention_sw', base_target),
                                      (2, 'attention_block', 'attention_hw', cordic_target),
                                      (3, 'banana', 'banana', base_target)]:
        directory = args.artifacts / name
        artifact = directory / 'program.mlirbc'
        data = np.load(directory / 'input.npy')
        options = CompileOptions(target=target, symbol=symbol, math_mode='freestanding',
                                 allow_approximation=True, gemm_policy=args.gemm_policy,
                                 specialize_matmuls=not args.no_specialize_matmuls)
        header = out / (symbol + '.h')
        report = compile_stablehlo(artifact, header, options)
        outputs, calls, native_report = native_reference(artifact, options, data)
        if tpu_placement(report) != tpu_placement(native_report):
            raise ValueError('Native reference and board target disagree on TPU placement')
        np.testing.assert_allclose(outputs[0].ravel(),
                                   np.load(directory / 'expected-native.npy').ravel(), rtol=5e-6, atol=5e-6)
        np.save(out / (symbol + '-expected.npy'), outputs[0])
        report['expected_backend_calls'] = calls
        (out / (symbol + '-report.json')).write_text(json.dumps(report, indent=2) + '\n')
        if mode != 2:
            fixture.append(f'static const float input_{mode}[]={{' +
                           ','.join(float(value).hex() + 'f' for value in data.ravel()) + '};')
        records.append({'mode': mode, 'name': name, 'symbol': symbol, 'target': target.name,
                        'words': report['signature']['outputs'][0]['bytes'] // 4,
                        'expected_backend_calls': calls, 'gemm_policy': args.gemm_policy,
                        'placement': report['placement'], 'expected_file': symbol + '-expected.npy',
                        'reference': 'Native generated C from this build; original reference within 5e-6 tolerance'})
        sources.update({str(path.resolve()): sha256(path) for path in (artifact, directory / 'input.npy', header)})
    (out / 'fixture.h').write_text('\n'.join(fixture) + '\n')
    sources[str(out / 'fixture.h')] = sha256(out / 'fixture.h')
    (out / 'modes.json').write_text(json.dumps(records, indent=2) + '\n')
    if args.headers_only:
        print('Prepared headers and placement reports; firmware was not rebuilt.')
        return
    build = compile_firmware(ROOT / 'sidequests/showcase/firmware.c', [out], out, args.optimization, args.tpu_transport, 'uart', ram_kib=args.ram_kib)
    build.update(schema_version=1, gemm_policy=args.gemm_policy, modes=records,
                 specialize_matmuls=not args.no_specialize_matmuls,
                 capabilities=['compact-coordinates-v1'],
                 reference_sha256={record['expected_file']: sha256(out / record['expected_file']) for record in records},
                 generated_and_input_sha256=sources, artifact_dir=str(args.artifacts.resolve()))
    (out / 'build-manifest.json').write_text(json.dumps(build, indent=2) + '\n')
    print((out / 'size.log').read_text().strip())
    print(json.dumps({'gemm_policy': args.gemm_policy, 'optimization': args.optimization,
                      'backend_calls_per_mode': [record['expected_backend_calls'] for record in records],
                      'memory': build['memory'], 'firmware': str(out / 'firmware.elf')}))


if __name__ == '__main__':
    main()
