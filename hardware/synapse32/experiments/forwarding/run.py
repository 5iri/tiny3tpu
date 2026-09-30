#!/usr/bin/env python3
"""Isolated production-RTL equivalence, CPU tests and XC7 resource comparison."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = Path(os.environ.get('SYNAPSE32_SOURCE', str(ROOT.parent / 'synapse32')))
BASE = HERE.parent / 'divider'
YOSYS = os.environ.get('YOSYS', '/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
os.environ.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')


def sources(candidate):
    files = [BASE / 'riscv_cpu.v', (HERE if candidate else BASE) / 'execution_unit.v',
             BASE / 'alu.v', BASE / 'divider.v', SOURCE / 'rtl/memory_unit.v',
             SOURCE / 'rtl/writeback.v']
    files += [p for folder in ('core_modules', 'pipeline_stages')
              for p in sorted((SOURCE / 'rtl' / folder).glob('*.v'))
              if p.name not in ('alu.v', 'divider.v')]
    return files


def read(files, top):
    # No FORMAL define: divider ALU's complete production branch is required.
    return ('read_slang --allow-use-before-declare --single-unit --top ' + top +
            ' -I' + str(SOURCE / 'rtl/include') + ' ' + ' '.join(map(str, files)) + ';')


def run(command, log):
    with log.open('w') as out:
        subprocess.run(command, stdout=out, stderr=subprocess.STDOUT, check=True)


def yosys(script, build, name):
    (build / (name + '.ys')).write_text(script + '\n')
    run([YOSYS, '-Q', '-T', '-m', 'slang', '-p', script], build / (name + '.log'))


def prove(build):
    script = ''
    for candidate, name in ((False, 'gold'), (True, 'gate')):
        files = [(HERE if candidate else BASE) / 'execution_unit.v', BASE / 'alu.v',
                 SOURCE / 'rtl/core_modules/csr_exec.v']
        script += read(files, 'execution_unit') + '''
            hierarchy -check -top execution_unit;
            proc; flatten; opt; check -assert; scc -expect 0;
            select -assert-count 3 t:$mul;
            select -assert-none t:$div t:$mod;
        ''' + f'rename execution_unit {name}; design -stash {name};\n'
    script += '''
        design -copy-from gold -as gold gold;
        design -copy-from gate -as gate gate;
        equiv_make gold gate equiv;
        hierarchy -top equiv;
        equiv_simple;
        equiv_status -assert;
    '''
    yosys(script, build, 'equivalence')


def synth(build):
    summary = {}
    for candidate, name in ((False, 'baseline'), (True, 'candidate')):
        script = read(sources(candidate), 'riscv_cpu') + f'''
            hierarchy -check -top riscv_cpu;
            proc; opt; check -assert; scc -expect 0;
            select -assert-none t:$div t:$mod t:$divfloor t:$modfloor;
            stat; write_json {build}/{name}.coarse.json;
            synth_xilinx -family xc7 -top riscv_cpu -noiopad -noclkbuf;
            check -assert; stat; write_json {build}/{name}.xc7.json;
        '''
        yosys(script, build, name)
        net = json.loads((build / (name + '.xc7.json')).read_text())
        counts = collections.Counter(c['type'] for c in net['modules']['riscv_cpu']['cells'].values())
        summary[name] = dict(sorted(counts.items()))
        summary[name]['TOTAL'] = sum(counts.values())
        summary[name]['LUT_TOTAL'] = sum(counts[f'LUT{i}'] for i in range(1, 7))
    (build / 'resources.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)


def test(build):
    pass_lines = {}
    for candidate, name in ((False, 'baseline'), (True, 'candidate')):
        for gated in (0, 1):
            tag = f'{name}-gated{gated}'
            obj = build / ('obj-' + tag)
            run(['verilator', '--binary', '--timing', '-j', '2', '-Wno-fatal',
                 '--top-module', 'cpu_tb', f'-GGATED={gated}', '--Mdir', str(obj),
                 '-DSYNAPSE32_CLOCK_SIM', '-I' + str(SOURCE / 'rtl/include'),
                 *map(str, sources(candidate)), str(HERE.parents[1] / 'synapse32_memory_sequencer.sv'),
                 str(HERE.parents[1] / 'synapse32_clock_enable.sv'), str(BASE / 'cpu_tb.sv')],
                build / (tag + '-compile.log'))
            run([str(obj / 'Vcpu_tb')], build / (tag + '.log'))
            output = (build / (tag + '.log')).read_text()
            lines = [line for line in output.splitlines() if line.startswith(f'PASS GATED={gated} ')]
            assert len(lines) == 1, f'Missing PASS marker: {tag}'
            pass_lines[tag] = lines[0]
            print(output, flush=True)
    for gated in (0, 1):
        assert pass_lines[f'baseline-gated{gated}'] == pass_lines[f'candidate-gated{gated}']
    (build / 'results.json').write_text(json.dumps(pass_lines, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prove', 'test', 'synth'])
    args = parser.parse_args()
    build = Path(tempfile.mkdtemp(prefix=args.mode + '.', dir=HERE))
    print('Evidence:', build, flush=True)
    files = set(sources(False) + sources(True))
    files.update((SOURCE / 'rtl/include').glob('*.vh'))
    files.update([BASE / 'cpu_tb.sv', Path(__file__), HERE.parents[1] / 'synapse32_memory_sequencer.sv',
                  HERE.parents[1] / 'synapse32_clock_enable.sv'])
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    (build / 'sources.sha256.json').write_text(json.dumps(before, indent=2) + '\n')
    run([YOSYS, '-V'], build / 'yosys-version.log')
    run(['verilator', '--version'], build / 'verilator-version.log')
    globals()[args.mode](build)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in before.items())
    evidence = HERE / 'evidence'
    evidence.mkdir(exist_ok=True)
    report = dict(mode=args.mode, build=str(build), source_hashes_unchanged=True,
                  sources_sha256=before,
                  yosys=(build / 'yosys-version.log').read_text().strip(),
                  verilator=(build / 'verilator-version.log').read_text().strip())
    if args.mode == 'prove':
        report['proof_summary'] = (build / 'equivalence.log').read_text().split('Executing EQUIV_STATUS pass.')[-1].strip()
        report['scope'] = 'All execution_unit outputs and matched internal wires, unrestricted two-state inputs; full production ALU; no FORMAL define, assumptions or blackboxes.'
    elif args.mode == 'synth':
        report['resources'] = json.loads((build / 'resources.json').read_text())
    else:
        report['results'] = json.loads((build / 'results.json').read_text())
    (evidence / (args.mode + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print('PASS', args.mode, '(source hashes unchanged)', flush=True)


if __name__ == '__main__':
    main()
