#!/usr/bin/env python3
"""Prove the actual atomic result/controls/reservation state for all inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from prepare import ATOMIC, ROOT, prepare

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args(); source = a.source.resolve(); out = a.out.resolve()
overlay = prepare(source, out)
inputs = {'clk':1, 'rst':1, 'instr_id_mem':7, 'mem_addr_mem':32,
          'rs2_value_mem':32, 'mem_read_data':32,
          'non_atomic_store_write_enable':1, 'non_atomic_store_write_addr':32}
outputs = {'is_lr_w':1, 'is_sc_w':1, 'is_amo_w':1, 'atomic_read_enable':1,
           'atomic_write_enable':1, 'sc_success':1, 'sc_result':32, 'atomic_new_word':32}
def width(n): return '' if n == 1 else f'[{n-1}:0] '
h = 'module equiv('+','.join('input '+width(n)+k for k,n in inputs.items())+',output same);\n'
for prefix, module in [('gold','atomic_lsu'), ('gate','atomic_lsu_parallel')]:
    h += ''.join('wire '+width(n)+prefix+'_'+k+';\n' for k,n in outputs.items())
    ports = ['.'+k+'('+k+')' for k in inputs]+['.'+k+'('+prefix+'_'+k+')' for k in outputs]
    h += module+' '+prefix+'('+','.join(ports)+');\n'
checks = [f'gold_{k} == gate_{k}' for k in outputs]+['gold.lr_valid == gate.lr_valid','gold.lr_addr == gate.lr_addr']
h += 'assign same = '+' && '.join('('+c+')' for c in checks)+';\nendmodule\n'
(out/'harness.sv').write_text(h)
defines = ROOT.parent/'synapse32/rtl/include/instr_defines.vh'
script = out/'proof.ys'
script.write_text(f'read_slang --top equiv -I{defines.parent} {ATOMIC} {out/"atomic_lsu_parallel.v"} {out/"harness.sv"}\n'
                  'prep -top equiv; flatten; async2sync; opt; check -assert; '
                  'sat -seq 3 -tempinduct -maxsteps 12 -set-init-zero -prove same 1 -verify;\n')
yosys = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
with (out/'proof.log').open('w') as log:
    rc = subprocess.run([str(yosys),'-Q','-T','-m','slang','-s',str(script)], stdout=log, stderr=subprocess.STDOUT).returncode
paths = list(source.glob('*.v'))+list(overlay.glob('*.v'))+[ATOMIC, defines, out/'atomic_lsu_parallel.v', out/'harness.sv', script, out/'proof.log', yosys, Path(__file__).resolve(), Path(__file__).with_name('prepare.py').resolve()]
result = dict(passed=rc==0, claim='Inductive equality of every actual atomic module output and reservation state for arbitrary instruction IDs, operands, addresses, reset and store notifications. CPU connection renamed to the exact proven embedded module; all other CPU bytes unchanged.',
              sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
assert result['passed'], out/'proof.log'
print('PASS atomic output, control and reservation-state equivalence')
