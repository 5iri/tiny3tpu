#!/usr/bin/env python3
"""Frozen CSR + bootdecode overlay; serial proofs/synthesis, exactly one route.

All generated artifacts go into a unique /tmp directory. Production sources,
build outputs and sibling experiments are read-only. No divider substitution.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CPU = ROOT.parent / 'synapse32'
YOSYS = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
PROOF_YOSYS = Path('/opt/homebrew/bin/yosys')
NEXTPNR = Path('/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx')
CHIPDB = Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin')
OUT = Path(tempfile.mkdtemp(prefix='tiny3tpu-combined-', dir='/tmp'))
print(OUT, flush=True)
ENV = {k: v for k, v in os.environ.items() if not k.startswith('NEXTPNR_')}
ENV.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', VECLIB_MAXIMUM_THREADS='2')
manifest = {'out': str(OUT), 'commands': [], 'route_count': 0,
            'synthesis_jobs_max': 1, 'thread_environment': {k: ENV[k] for k in
            ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')},
            'diagnostic_only': True, 'physical_ready': False}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save():
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def run(name, command):
    entry = {'name': name, 'argv': list(map(str, command))}
    manifest['commands'].append(entry)
    save()
    print(name, flush=True)
    with (OUT / (name + '.log')).open('w') as log:
        result = subprocess.run(entry['argv'], cwd=OUT, env=ENV,
                                stdout=log, stderr=subprocess.STDOUT)
    entry['returncode'] = result.returncode
    save()
    if result.returncode:
        raise RuntimeError(f'{name} failed: {OUT / (name + ".log")}')


def proof(name, script, tool=PROOF_YOSYS):
    path = OUT / (name + '.ys')
    path.write_text(script + '\n')
    run(name, [tool, '-Q', '-T', '-s', path])


script = (ROOT / 'build-ddr/synth.ys').read_text()
sources = [Path(p) for p in re.findall(r'(?<=\s)/[^\s\"]+\.(?:vh|sv|v)(?=\s|$)', script)]
inputs = set(sources) | set((CPU / 'rtl').rglob('*.vh')) | {
    ROOT / 'build-ddr/synth.ys', ROOT / 'build-ddr/soc.json',
    ROOT / 'build-ddr/kc705.xdc', ROOT / 'build-ddr/firmware.hex',
    ROOT / 'build-ddr/synapse-current-baseline.log', YOSYS, PROOF_YOSYS,
    NEXTPNR, CHIPDB, HERE.parent / 'interconnect/check.py',
    HERE.parent / 'interconnect/compare_full.py',
    HERE.parent / 'cpu/csr_exec.v', HERE.parent / 'interconnect/synapse32_dram_soc.sv'}
manifest['input_sha256'] = {str(p): digest(p) for p in sorted(inputs)}
assert digest(CHIPDB) == 'd3d90cb680525dcf42b19dde35df9660ca7a9a48b5865bd33404129a2595b284'
assert digest(ROOT / 'build-ddr/kc705.xdc') == 'e1c892563932bfae60eddf7253e123a06239bce6c2c1ac3928186ba00921f10c'
assert 'DCI_CASCADE' in (ROOT / 'build-ddr/kc705.xdc').read_text()
substitutions = {
    CPU / 'rtl/core_modules/csr_exec.v': HERE.parent / 'cpu/csr_exec.v',
    ROOT / 'hardware/synapse32/synapse32_dram_soc.sv':
        HERE.parent / 'interconnect/synapse32_dram_soc.sv'}
for original, candidate in substitutions.items():
    frozen = OUT / candidate.name
    frozen.write_bytes(candidate.read_bytes())
    assert script.count(str(original)) == 1
    script = script.replace(str(original), str(frozen))
assert script.count(str(ROOT / 'build-ddr/soc.json')) == 1
script = script.replace(str(ROOT / 'build-ddr/soc.json'), str(OUT / 'soc.json'))
(OUT / 'synth.ys').write_text(script)
manifest['substitutions'] = {str(k): str(OUT / v.name) for k, v in substitutions.items()}
manifest['overlay_sha256'] = {str(OUT / v.name): digest(OUT / v.name) for v in substitutions.values()}
save()
run('yosys-version', [YOSYS, '-V'])
run('nextpnr-version', [NEXTPNR, '--version'])
proof('csr_equiv', f'''read_verilog -sv -I{CPU}/rtl/include {CPU}/rtl/core_modules/csr_exec.v
rename csr_exec gold
read_verilog -sv -I{CPU}/rtl/include {OUT}/csr_exec.v
rename csr_exec gate
proc; memory; opt
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple
equiv_status -assert''', YOSYS)
# Reuse the reviewed controller abstraction against the frozen overlay itself.
spec = importlib.util.spec_from_file_location('bootcheck', HERE.parent / 'interconnect/check.py')
bootcheck = importlib.util.module_from_spec(spec)
# Avoid Python cache writes to the sibling experiment.
exec(compile(Path(spec.origin).read_text(), spec.origin, 'exec'), bootcheck.__dict__)
for name, source in [('gold', ROOT / 'hardware/synapse32/synapse32_dram_soc.sv'),
                     ('gate', OUT / 'synapse32_dram_soc.sv')]:
    (OUT / (name + '.sv')).write_text(bootcheck.controller(source.read_text(), name))
sizes = [16384, 3, 32768, 1, 2, 536870912, 536870913, 1073741824]
for words in sizes:
    proof(f'boot_equiv_{words}', f'''read_verilog -sv gold.sv gate.sv
chparam -set BOOT_WORDS {words} gold gate
proc; opt
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple
equiv_induct -seq 4
equiv_status -assert''')
manifest['equivalence'] = {'csr': 'PASS, two-state combinational',
    'boot_controller': 'PASS, compositional induction', 'boot_words': sizes,
    'limitation': 'Not a full CPU/DDR or four-state proof; RAM contents abstracted.'}
save()
run('synthesis', [YOSYS, '-Q', '-T', '-m', 'slang', '-s', OUT / 'synth.ys'])
run('preservation', ['python3', HERE.parent / 'interconnect/compare_full.py',
                     ROOT / 'build-ddr/soc.json', OUT / 'soc.json'])
run('combined-audit', ['python3', HERE / 'audit.py', OUT])
assert manifest['input_sha256'] == {str(p): digest(p) for p in sorted(inputs)}
manifest['soc_sha256'] = digest(OUT / 'soc.json')
manifest['route_count'] = 1
save()
run('route', [NEXTPNR, '--chipdb', CHIPDB, '--json', OUT / 'soc.json',
    '--xdc', ROOT / 'build-ddr/kc705.xdc', '--freq', '100', '--seed', '4',
    '--placer', 'heap', '--write', OUT / 'soc_routed.json',
    '--report', OUT / 'timing.json', '--log', OUT / 'nextpnr.log'])
manifest['final_fmax'] = json.loads((OUT / 'timing.json').read_text())['fmax']
manifest['inputs_unchanged'] = manifest['input_sha256'] == {str(p): digest(p) for p in sorted(inputs)}
manifest['overlays_unchanged'] = all(digest(p) == h for p, h in manifest['overlay_sha256'].items())
manifest['output_sha256'] = {p.name: digest(p) for p in OUT.iterdir()
                             if p.is_file() and p.name != 'manifest.json'}
save()
assert manifest['inputs_unchanged'] and manifest['overlays_unchanged']
print(json.dumps(manifest['final_fmax'], indent=2), flush=True)
