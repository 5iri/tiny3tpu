#!/usr/bin/env python3
"""Run the parent's new collision matrix with the candidate in both clock modes."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile

HERE = Path(__file__).resolve().parent
r = runpy.run_path(str(HERE / 'run.py'))
build = Path(tempfile.mkdtemp(prefix='collision.', dir=HERE))
print('Evidence:', build, flush=True)
files = r['sources'](True)
extra = [HERE.parents[1] / 'synapse32_memory_sequencer.sv',
         HERE.parents[1] / 'synapse32_clock_enable.sv',
         r['BASE'] / 'cpu_collision_tb.sv']
inputs = files + extra + list((r['SOURCE'] / 'rtl/include').glob('*.vh')) + [Path(__file__), HERE / 'run.py']
hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
report = dict(build=str(build), sources_sha256=hashes, results={})
for gated in (0, 1):
    obj = build / f'obj{gated}'
    r['run'](['verilator', '--binary', '--timing', '-j', '2', '-Wno-fatal',
              '--top-module', 'cpu_collision_tb', f'-GGATED={gated}', '--Mdir', str(obj),
              '-DSYNAPSE32_CLOCK_SIM', '-I' + str(r['SOURCE'] / 'rtl/include'),
              *map(str, files + extra)], build / f'compile{gated}.log')
    log = build / f'run{gated}.log'
    r['run']([str(obj / 'Vcpu_collision_tb')], log)
    expected = f'PASS CPU collision matrix GATED={gated} cases=64 irq-boundaries=24 fault-priority=40 stores=256'
    assert expected in log.read_text().splitlines(), f'Missing coverage PASS: {log}'
    report['results'][str(gated)] = expected
    print(expected, flush=True)
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
report['source_hashes_unchanged'] = True
(HERE / 'evidence/collision.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS candidate collision: 128 cases, source hashes unchanged', flush=True)
