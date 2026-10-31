#!/usr/bin/env python3
"""Compare result-window reads and constant prepacking on full simulated SoC RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--cordic', action='store_true')
    parser.add_argument('--synapse32-dir', type=Path)
    args = parser.parse_args()
    if bool(args.artifact) != bool(args.input):
        parser.error('--artifact and --input must be supplied together')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    common = [sys.executable, str(ROOT / 'tests/test_stablehlo_soc.py'),
              '--no-affine', '--profile', '--gemm-policy', 'tpu']
    if args.artifact:
        common += ['--artifact', str(args.artifact.resolve()),
                   '--input', str(args.input.resolve())]
    if args.cordic:
        common.append('--cordic')
    if args.synapse32_dir:
        common += ['--synapse32-dir', str(args.synapse32_dir.resolve())]
    modes = (
        ('accumulation_only', ['--legacy-result-reads', '--no-prepack-constants']),
        ('result_window_only', ['--no-prepack-constants']),
        ('prepacking_only', ['--legacy-result-reads']),
        ('both', []),
    )
    reports = {}
    for name, flags in modes:
        destination = out / name
        print(f'Running {name}', flush=True)
        subprocess.run([*common, '--out', str(destination), *flags], check=True)
        profile = json.loads((destination / 'profile.json').read_text())
        compile_report = json.loads((destination / 'compile-report.json').read_text())
        if '--no-prepack-constants' in flags and profile['packed_backend_calls']:
            raise RuntimeError('Disabled prepacking still used a packed callback')
        reports[name] = dict(profile=profile, compiler=compile_report,
                             firmware_size=(destination / 'size.log').read_text().strip())
    baseline = reports['accumulation_only']['profile']
    for report in reports.values():
        profile = report['profile']
        if (profile['backend_calls'] != baseline['backend_calls'] or
                profile['verified_words'] != baseline['verified_words']):
            raise RuntimeError('A/B modes performed different work')
        report['speedup_vs_accumulation_only'] = baseline['total_cycles'] / profile['total_cycles']
    sources = ['src/mmio_backend.c', 'include/tiny3tpu_runtime.h',
               'include/tiny3tpu_mmio_backend.h', 'tools/program/c_backend.py',
               'multi-core/tiny3tpu_axi.sv', 'tests/test_stablehlo_soc.py']
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}
    inputs = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (args.artifact, args.input) if path is not None}
    summary = dict(schema='tiny3tpu-data-movement-profile-v1',
                   scope='Instrumented VexRiscv+TPU RTL with accumulation enabled in every mode; '
                         'separately compiled firmware, no physical board or UART timing',
                   source_sha256=hashes, input_sha256=inputs, modes=reports)
    (out / 'comparison.json').write_text(json.dumps(summary, indent=2) + '\n')
    for name, report in reports.items():
        print(f'{name}: {report["profile"]["total_cycles"]:,} cycles, '
              f'{report["speedup_vs_accumulation_only"]:.3f}x baseline speed')
    print(f'Report: {out / "comparison.json"}')


if __name__ == '__main__':
    main()
