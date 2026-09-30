#!/usr/bin/env python3
"""Prove all outputs of the actual branch case for arbitrary bit-vector inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from prepare import branch_body, prepare

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();source=a.source.resolve();out=a.out.resolve();overlay=prepare(source,out)
root=Path(__file__).resolve().parents[4]
defines=root.parent/'synapse32/rtl/include/instr_defines.vh'
inputs={'instr_id':7,'rs1_value':32,'rs2_value':32,'pc_input':32,'imm':32,
        'mtvec':32,'stvec':32,'delegate_instr_addr_misaligned':1}
outputs={'target_addr':32,'jump_signal_comb':1,'jump_addr_comb':32,
         'flush_pipeline_comb':1,'trap_to_supervisor_comb':1,
         'instruction_address_misaligned_exception_comb':1,'exception_tval_comb':32}
def width(n):return '' if n==1 else f'[{n-1}:0] '
h='`include "instr_defines.vh"\n'
for prefix,path in [('gold',source/'execution_unit.v'),('gate',overlay/'execution_unit.v')]:
    h+='module '+prefix+'('+','.join(['input '+width(n)+k for k,n in inputs.items()]+['output reg '+width(n)+k for k,n in outputs.items()])+');\n'
    h+='always @* begin\n'+''.join(k+'=0;\n' for k in outputs)
    h+="case (7'b1100011)\n"+branch_body(path.read_text())+'endcase\nend\nendmodule\n'
h+='module equiv('+','.join('input '+width(n)+k for k,n in inputs.items())+',output same);\n'
for prefix in ['gold','gate']:
    h+=''.join('wire '+width(n)+prefix+'_'+k+';\n' for k,n in outputs.items())
    h+=prefix+' '+prefix+'_inst('+','.join(['.'+k+'('+k+')' for k in inputs]+['.'+k+'('+prefix+'_'+k+')' for k in outputs])+');\n'
h+='assign same='+' && '.join('(gold_'+k+' == gate_'+k+')' for k in outputs)+';\nendmodule\n'
(out/'harness.sv').write_text(h)
script=out/'proof.ys';script.write_text(f'read_slang --top equiv -I{defines.parent} {out/"harness.sv"}\nprep -top equiv; flatten; opt; check -assert; sat -prove same 1 -verify;\n')
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
with (out/'proof.log').open('w') as log:
    rc=subprocess.run([str(yosys),'-Q','-T','-m','slang','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
paths=list(source.glob('*.v'))+list(overlay.glob('*.v'))+[defines,out/'harness.sv',script,out/'proof.log',yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]
r=dict(passed=rc==0,claim='Actual branch case outputs including target, redirect, delegation and misalignment tval are equal for every instruction ID, operand pair, PC, immediate and trap vector. Surrounding defaults/priority and all registered stages remain byte identical.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS all branch-case outputs for arbitrary inputs')
