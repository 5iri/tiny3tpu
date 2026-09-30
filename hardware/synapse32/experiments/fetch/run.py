#!/usr/bin/env python3
"""Snapshot inputs and compare only the sequencer, without changing shared files.

All builds/evidence stay in this experiment. No synthesis, placement or route.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CPU = Path(os.environ.get('SYNAPSE32_SOURCE', ROOT.parent / 'synapse32'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=['all', 'unit', 'cpu', 'dram'], default='all')
    parser.add_argument('--entries', type=int, choices=[2, 16, 64], default=16)
    args = parser.parse_args()
    out = Path(tempfile.mkdtemp(prefix='run-', dir=HERE))
    snap = out / 'snapshot'
    root, cpu = snap / 'root', snap / 'cpu'
    report = {'out': str(out), 'commands': [], 'inputs': {}, 'results': {},
              'baseline': 'divider overlay; original CSR, SoC and sequencer',
              'candidate': f'same snapshot, only sequencer replaced; {args.entries} entries',
              'entries': args.entries,
              'route_count': 0}
    print(out, flush=True)

    def save():
        (out / 'evidence.json').write_text(json.dumps(report, indent=2) + '\n')

    paths = set()
    for folder in ['hardware/synapse32', 'multi-core', 'systolic_array/rtl', 'src', 'include', 'tests']:
        paths.update(p for p in (ROOT / folder).glob('*') if p.is_file() and
                     p.suffix in ('.v', '.sv', '.h', '.c', '.cpp', '.S', '.ld', '.cmake'))
    paths.update((HERE.parent / 'divider').glob('*.v'))
    paths.update((HERE.parent / 'divider').glob('*tb.sv'))
    paths.update([HERE / 'synapse32_memory_sequencer.sv', HERE / 'fetch_tb.sv', Path(__file__)])
    for p in sorted(paths):
        dest = root / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        report['inputs'][str(p)] = sha(dest)
    for p in sorted((CPU / 'rtl').rglob('*')):
        if p.is_file() and p.suffix in ('.v', '.vh'):
            dest = cpu / p.relative_to(CPU)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
            report['inputs'][str(p)] = sha(dest)
    frozen = {str(p): sha(p) for p in snap.rglob('*') if p.is_file()}
    report['snapshot_sha256'] = frozen
    report['shared_harness_sha256'] = sha(root / 'tests/synapse32_dram_test.cpp')
    save()
    env = dict(os.environ, OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')

    def run(tag, argv, marker=None):
        record = {'tag': tag, 'argv': list(map(str, argv))}
        report['commands'].append(record)
        save()
        print(tag, flush=True)
        log = out / (tag + '.log')
        with log.open('w') as stream:
            result = subprocess.run(record['argv'], cwd=out, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        record['returncode'] = result.returncode
        text = log.read_text()
        save()
        if result.returncode or (marker and marker not in text) or re.search(r'^FAIL', text, re.M):
            raise RuntimeError(f'{tag} failed: {log}\n{text[-3000:]}')
        if marker:
            report['results'][tag] = [s for s in text.splitlines() if 'PASS' in s or 'METRICS' in s]
            print('\n'.join(s for s in report['results'][tag] if not s.startswith('PASS collision ')), flush=True)
        save()
        return text

    for tool in ['verilator', 'iverilog', 'riscv64-unknown-elf-gcc']:
        run(tool + '-version', [tool, '-V' if tool=='iverilog' else '--version'])
    board = root / 'hardware/synapse32'
    div = board / 'experiments/divider'
    candidate = board / 'experiments/fetch/synapse32_memory_sequencer.sv'
    if args.entries != 16:
        configured = out / 'configured-sequencer.sv'
        text = candidate.read_text()
        assert text.count('parameter integer FETCH_ENTRIES = 16') == 1
        configured.write_text(text.replace('parameter integer FETCH_ENTRIES = 16',
                                          f'parameter integer FETCH_ENTRIES = {args.entries}'))
        candidate = configured
    report['candidate_sha256'] = sha(candidate)
    variants = [('baseline', board / 'synapse32_memory_sequencer.sv'), ('candidate', candidate)]
    if args.suite in ('all', 'unit'):
        for name, sequencer in variants:
            for tb, test in [('tb_synapse32_memory_sequencer', root / 'tests/tb_synapse32_memory_sequencer.sv'),
                             ('fetch_tb', board / 'experiments/fetch/fetch_tb.sv')]:
                tag = name + '-' + tb
                run(tag + '-compile', ['iverilog', '-g2012', '-DSYNAPSE32_CLOCK_SIM', '-s', tb,
                    '-o', out / (tag + '.vvp'), sequencer, board / 'synapse32_clock_enable.sv', test])
                run(tag, ['vvp', out / (tag + '.vvp')], 'PASS')
    if args.suite in ('all', 'cpu'):
        files = [div / (n + '.v') for n in ['riscv_cpu', 'execution_unit', 'alu', 'divider']]
        files += [cpu / 'rtl/memory_unit.v', cpu / 'rtl/writeback.v']
        files += [p for folder in ['core_modules', 'pipeline_stages']
                  for p in sorted((cpu / 'rtl' / folder).glob('*.v')) if p.name not in ('alu.v', 'divider.v')]
        for name, sequencer in variants:
            for tb in ['cpu_tb', 'cpu_collision_tb']:
                tag = name + '-' + tb
                obj = out / ('obj-' + tag)
                run(tag + '-compile', ['verilator', '--binary', '--timing', '-j', '2', '-Wno-fatal',
                    '--top-module', tb, '-GGATED=1', '--Mdir', obj, '-DSYNAPSE32_CLOCK_SIM',
                    '-I' + str(cpu / 'rtl/include'), *files, sequencer,
                    board / 'synapse32_clock_enable.sv', div / (tb + '.sv')])
                run(tag, [obj / ('V' + tb)], 'PASS')
        metrics = {}
        for name, _ in variants:
            line = next(s for s in report['results'][name + '-cpu_tb'] if s.startswith('PASS GATED='))
            metrics[name] = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)}
        assert {k: v for k, v in metrics['baseline'].items() if k!='system_cycles'} == {
            k: v for k, v in metrics['candidate'].items() if k!='system_cycles'}
        assert report['results']['baseline-cpu_collision_tb'] == report['results']['candidate-cpu_collision_tb']
        report['cpu_metrics'] = metrics
    if args.suite in ('all', 'dram'):
        template = (root / 'tests/run_synapse32_cpu_test.cmake').read_text()
        needle = '"${SOURCE_DIR}/hardware/synapse32/synapse32_memory_sequencer.sv"'
        assert template.count(needle) == 1
        metrics = {}
        for name, sequencer in variants:
            script = out / (name + '-dram.cmake')
            # The runner is the shared CMake script with exactly one RTL source
            # substitution. The C++ harness, firmware and other RTL are frozen.
            script.write_text(template.replace(needle, '"' + str(sequencer) + '"'))
            log = run(name + '-dram', ['cmake', '-DSOURCE_DIR=' + str(root),
                '-DBINARY_DIR=' + str(out / (name + '-dram')),
                '-DSYNAPSE32_DIR=' + str(cpu), '-DCPU_OVERLAY_DIR=' + str(div),
                '-DVERILATOR=' + shutil.which('verilator'),
                '-DRISCV_GCC=' + shutil.which('riscv64-unknown-elf-gcc'),
                '-DRISCV_OBJCOPY=' + shutil.which('riscv64-unknown-elf-objcopy'),
                '-DDRAM_TEST=ON', '-P', script], 'PASS Synapse32 variable-latency DRAM -> TPU:')
            metrics[name] = json.loads(re.search(r'METRICS (\{[^\n]+\})', log)[1])
        for key in ['workload', 'memory_model', 'external_reads', 'external_writes',
                    'external_read_bytes', 'external_write_bytes', 'completed_transactions', 'checked_results']:
            assert metrics['baseline'][key] == metrics['candidate'][key], key
        assert sha(out / 'baseline-dram/smoke.hex') == sha(out / 'candidate-dram/smoke.hex')
        report['firmware_hex_sha256'] = sha(out / 'baseline-dram/smoke.hex')
        report['dram_metrics'] = metrics
    assert frozen == {p: sha(Path(p)) for p in frozen}, 'snapshot changed'
    report['snapshot_unchanged'] = True
    report['live_input_changes'] = [p for p, h in report['inputs'].items() if sha(Path(p)) != h]
    save()
    evidence = HERE / 'evidence' / f'{args.suite}-{args.entries}'
    evidence.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out / 'evidence.json', evidence / 'evidence.json')
    for tag in report['results']:
        shutil.copyfile(out / (tag + '.log'), evidence / (tag + '.log'))
    print('PASS isolated experiment:', out / 'evidence.json', flush=True)


if __name__ == '__main__':
    main()
