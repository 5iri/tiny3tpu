#!/usr/bin/env python3
"""Prove, simulate and synthesize isolated edits to the best expanded candidate.

Uses hash-checked prepared RTL snapshots. Does not mutate the original drivers,
rebuild their generators, alter firmware or constraints, or claim timing closure.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from prepare import FIRST, patch_dram, patch_soc
from terminal import patch_dma, prove_dma
from fifo import patch_fifo, prove_fifo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
YOSYS = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(path):
    data = json.loads(Path(path).read_text())
    for key in ('sha256', 'output_sha256'):
        for name, value in data.get(key, {}).items():
            assert digest(name) == value, (str(path), name)
    return data


def run(command, logfile):
    print('Running', logfile, flush=True)
    with logfile.open('w') as log:
        rc = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
    if rc:
        print('\n'.join(logfile.read_text().splitlines()[-30:]))
        raise SystemExit(rc)


def write_record(path, data, paths):
    data['sha256'] = {str(p): digest(p) for p in paths}
    path.write_text(json.dumps(data, indent=2) + '\n')


def prepare(out):
    base = ROOT / 'build-ddr-dma-uart-reset'
    stress = ROOT / 'build-ddr-gemm-uart-reset'
    parent = ROOT / 'build-ddr-seeds-uart-reset-guided-graph/seed-8/manifest.json'
    evidence = [parent, base / 'system/results.json', stress / 'system/results.json',
                ROOT / 'build-uart-reset-control-proved/synthesis-comparison.json']
    for path in evidence:
        check(path)
    out.mkdir(parents=True, exist_ok=False)
    inputs = evidence + [HERE / 'run_fifo.py', HERE / 'prepare.py', HERE/'terminal.py', HERE/'fifo.py',
                          HERE.parent / 'boot-local-enable/prepare.py',
                          HERE.parent / 'boot-local-enable/prove.py', YOSYS]
    outputs = []
    for src in sorted(base.iterdir()):
        if src.suffix in ('.v', '.sv', '.c'):
            dest = out / src.name
            text = src.read_text()
            if src.name in ('synapse32_dram_soc.sv', 'synapse32_dram_soc_synth.sv'):
                text = patch_soc(text)
            if src.name == 'axi_dma_wr.v':
                text = patch_dma(text)
            dest.write_text(text)
            inputs.append(src); outputs.append(dest)
    for relative in ['board/synth.ys', 'board/boot_path.vh', 'board/firmware.hex',
                     'board/kc705.xdc', 'board/litedram/gateware/kc705_dram.v']:
        src = base / relative; dest = out / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.name in ('firmware.hex', 'kc705.xdc'):
            dest.write_bytes(src.read_bytes())
        else:
            text = src.read_text().replace(str(base), str(out))
            if src.name == 'kc705_dram.v':
                text = patch_fifo(patch_dram(text))
            dest.write_text(text)
        inputs.append(src); outputs.append(dest)
    assert digest(base/'board/firmware.hex') == digest(out/'board/firmware.hex')
    assert digest(base/'board/kc705.xdc') == digest(out/'board/kc705.xdc')
    for label, source in [('smoke', base), ('gemm', stress)]:
        dest = out / label; dest.mkdir()
        for name, src in [('run.cmake', source/'system/run.cmake'),
                          ('profile.cpp', source/'system/profile.cpp'),
                          ('stream_smoke.c', source/'stream_smoke.c')]:
            text = src.read_text().replace(str(source/'system'), str(dest)).replace(str(source), str(out))
            if name == 'run.cmake':
                text = text.replace(str(out/'stream_smoke.c'), str(dest/'stream_smoke.c'))
            target = dest / name; target.write_text(text)
            inputs.append(src); outputs.append(target)
    write_record(out/'prepared.json', dict(passed=True, parent=str(parent),
                 firmware_identical=True, constraints_identical=True,
                 source='Exact prepared parent snapshots with two explicit RTL patches.'), inputs+outputs)


def prove(out):
    check(out/'prepared.json')
    proof = out/'proof'; proof.mkdir(exist_ok=False)
    run([sys.executable, HERE.parent/'boot-local-enable/prove.py', '--soc',
         ROOT/'build-ddr-dma-uart-reset/synapse32_dram_soc.sv', '--out', proof/'boot'], proof/'boot.log')
    assert (proof/'boot/candidate.sv').read_bytes() == (out/'synapse32_dram_soc.sv').read_bytes()
    src = (ROOT/'build-ddr-dma-uart-reset/board/litedram/gateware/kc705_dram.v').read_text()
    # Extract the actual generated counter transitions and output predicates.
    block = re.search(r"    if \(\(main_write_aw_valid & main_write_aw_ready\)\) begin\n(.*?)    if \(main_write_w_buffer_syncfifo_re\)", src, re.S).group(1)
    prefix = block.split('            if ((((main_write_source_source_payload_burst')[0]
    prefix = '\n'.join(line for line in prefix.splitlines() if 'beat_offset' not in line)
    counter = '    if ((main_write_aw_valid & main_write_aw_ready)) begin\n' + prefix + '\n        end\n    end\n'
    reset = re.search(r'        main_write_beat_count <= 8\'d0;', src).group(0)
    exprs = '\n'.join(re.findall(r'^assign main_write_aw_(?:first|last|valid) = [^;]+;', src, re.M))
    harness = '''module equiv(input sys_clk, sys_rst, main_write_aw_ready,
input main_write_source_source_valid, input [7:0] main_write_source_source_payload_len,
output same);
reg [7:0] main_write_beat_count = 0;
wire main_write_aw_first, main_write_aw_last, main_write_aw_valid;
''' + exprs + '\nalways @(posedge sys_clk) begin\n' + counter + '\nif (sys_rst) begin\n'+reset+'\nend\nend\n' + FIRST + '''
assign same = main_write_first_q == main_write_aw_first;
endmodule
'''
    (proof/'first.v').write_text(harness)
    (proof/'first.ys').write_text(f'read_verilog {proof/"first.v"}\nprep -top equiv; flatten; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -prove same 1 -verify;\n')
    run([YOSYS, '-Q', '-T', '-s', proof/'first.ys'], proof/'first.log')
    write_record(proof/'results.json', dict(passed=True,
        claim='Local boot acceptance identical for all inputs and signed BOOT_WORDS; first-beat flag equals the actual counter zero predicate by temporal induction with arbitrary reset, ready, valid and len. Includes 255-to-zero wrap. All other board RTL unchanged.'),
        [out/'prepared.json', proof/'boot/results.json', proof/'first.v', proof/'first.ys',
         proof/'first.log', HERE/'run_fifo.py', HERE/'prepare.py'])
    prove_dma(out)
    prove_fifo(out)
    print('PASS boot, first-beat and full DMA equivalence', flush=True)


def simulate(out, label):
    check(out/'prepared.json'); check(out/'proof/results.json'); check(out/'dma-proof/results.json'); check(out/'fifo-proof/results.json')
    system = out/label
    source = ROOT/('build-ddr-dma-uart-reset' if label == 'smoke' else 'build-ddr-gemm-uart-reset')
    baseline = check(source/'system/results.json')
    cmd = [arg.replace(str(source/'system'), str(system)) for arg in baseline['command']]
    run(cmd, system/'run.log')
    lines = (system/'run.log').read_text().splitlines()
    result = {key.lower(): json.loads(next(line[len(key)+1:] for line in lines if line.startswith(key+' ')))
              for key in ('PROFILE','METRICS','DMA')}
    result['profile']['cpu_ipc'] = result['profile']['instructions']/result['profile']['cpu_edges']
    assert all(result[k] == baseline[k] for k in ('profile','metrics','dma'))
    assert (system/'smoke.bin').read_bytes() == (source/'system/smoke.bin').read_bytes()
    result.update(passed=True, all_profile_metrics_dma_exact=True, firmware_binary_identical=True,
                  litedram_frontend_simulated=False, command=cmd)
    write_record(system/'results.json', result, [out/'prepared.json', out/'proof/results.json',
        source/'system/results.json', system/'run.cmake', system/'profile.cpp', system/'run.log',
        system/'smoke.bin', system/'smoke.elf', HERE/'run_fifo.py'])
    print('PASS', label, {k: result['profile'][k] for k in ('instructions','cpu_edges','cpu_ipc')},
          result['metrics']['system_cycles'], flush=True)


def synth(out):
    for p in ['prepared.json', 'proof/results.json', 'dma-proof/results.json', 'fifo-proof/results.json', 'smoke/results.json', 'gemm/results.json']:
        assert check(out/p)['passed']
    board = out/'board'
    run([YOSYS, '-Q', '-T', '-m', 'slang', '-s', board/'synth.ys'], board/'synth.log')
    # Bind all sources in the exact synthesis script, including unchanged CPU/TPU.
    text = (board/'synth.ys').read_text()
    paths = [Path(s) for s in shlex.split(text)
             if s.startswith('/') and Path(s).suffix in ('.sv','.vh','.v')]
    paths += [out/'prepared.json', out/'proof/results.json', out/'smoke/results.json',
              out/'gemm/results.json', board/'soc.json', board/'synth.log', YOSYS,
              YOSYS.parents[1]/'share/yosys/xilinx/cells_sim.v',
              YOSYS.parents[1]/'share/yosys/xilinx/cells_xtra.v',
              YOSYS.parents[1]/'share/yosys/plugins/slang.so', HERE/'run_fifo.py']
    write_record(board/'synthesis.json', dict(passed=True, full_soc_timing_accepted=False), paths)
    print('PASS synthesis', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['prepare','prove','smoke','gemm','synth'])
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); out = a.out.resolve()
    if a.stage in ('smoke','gemm'):
        simulate(out, a.stage)
    else:
        globals()[a.stage](out)
