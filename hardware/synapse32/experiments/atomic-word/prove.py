#!/usr/bin/env python3
"""Prove actual atomic outputs with arbitrary forwarded bytes and bus inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from prepare import prepare, ASSIGN

ROOT = Path(__file__).resolve().parents[4]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args(); source = a.source.resolve(); out = a.out.resolve()
overlay = prepare(source, out)
cpu = (source / 'riscv_cpu.v').read_text()
gate = (overlay / 'riscv_cpu.v').read_text()
start = cpu.index('    // Read request for loads/LR/AMO.')
end = cpu.index('    // Use memory when the load/atomic read')
merge = cpu[start:end]
gate_merge = gate[gate.index('    // Read request for loads/LR/AMO.'):gate.index('    // Use memory when the load/atomic read')]
assert gate_merge.replace(ASSIGN, '') == merge
inputs = {'clk':1, 'rst':1, 'ex_mem_inst0_instr_id_out':7,
          'ex_mem_inst0_mem_addr_out':32, 'ex_mem_inst0_rs2_value_out':32,
          'module_read_data_in':32, 'non_atomic_store_write_enable':1,
          'non_atomic_store_write_addr':32, 'store_buf_valid':1,
          'store_buf_addr':32, 'store_buf_be':4, 'store_buf_data':32,
          'mem_unit_inst0_read_enable_out':1, 'mem_unit_inst0_read_addr_out':32,
          'mem_unit_inst0_load_type_out':3}
outputs = {'is_lr_w':1, 'is_sc_w':1, 'is_amo_w':1, 'atomic_read_enable':1,
           'atomic_write_enable':1, 'sc_success':1, 'sc_result':32, 'atomic_new_word':32}
def width(n): return '' if n == 1 else f'[{n-1}:0] '
h = ('`include "instr_defines.vh"\nmodule equiv(' +
     ','.join('input wire '+width(n)+k for k,n in inputs.items()) + ',output same);\n')
h += 'wire ex_mem_read_req, load_all_bytes_covered;\nwire [31:0] ex_mem_read_addr, atomic_read_word;\nwire [2:0] ex_mem_read_type;\nreg [31:0] mem_read_data_effective;\n'
for prefix, text in [('gold',cpu), ('gate',gate)]:
    for name,n in outputs.items(): h += 'wire '+width(n)+prefix+'_'+name+';\n'
    begin = text.index('    atomic_lsu atomic_lsu_inst0 (')
    finish = text.index('    );',begin)+len('    );')
    instance = text[begin:finish].replace('atomic_lsu_inst0',prefix)
    for name in outputs: instance = instance.replace(f'.{name}({name})',f'.{name}({prefix}_{name})')
    h += instance+'\n'
for name in ('is_lr_w','is_amo_w','atomic_read_enable'):
    h += f'wire {name} = gold_{name};\n'
h += gate_merge
checks = [f'gold_{k} == gate_{k}' for k in outputs]
checks += ['gold.lr_valid == gate.lr_valid','gold.lr_addr == gate.lr_addr']
h += 'assign same = '+ ' && '.join('('+c+')' for c in checks)+';\nendmodule\n'
(out/'harness.sv').write_text(h)
atomic = ROOT.parent/'synapse32/rtl/core_modules/atomic_lsu.v'
defines = ROOT.parent/'synapse32/rtl/include/instr_defines.vh'
script = out/'proof.ys'
script.write_text(f'read_slang --top equiv -I{defines.parent} {atomic} {out/"harness.sv"}\n'
                  'prep -top equiv; flatten; async2sync; opt; check -assert; '
                  'sat -seq 3 -tempinduct -maxsteps 12 -set-init-zero -prove same 1 -verify;\n')
yosys = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
with (out/'proof.log').open('w') as log:
    rc = subprocess.run([str(yosys),'-Q','-T','-m','slang','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
paths = list(source.glob('*.v'))+list(overlay.glob('*.v'))+[atomic,defines,script,out/'harness.sv',yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]
r = dict(passed=rc==0,claim='Actual atomic module outputs and reservation state match with arbitrary instruction IDs, memory/forwarding inputs, store-buffer state, reset and bus writes. Merge logic and instances extracted from exact CPU sources. Only atomic read-data connection changes; no cycles added.',
         sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n')
assert r['passed'], out/'proof.log'
print('PASS atomic outputs, reservation state and forwarded word equivalence')
