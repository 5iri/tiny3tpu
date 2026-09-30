#!/usr/bin/env python3
import argparse, hashlib, json, re, subprocess
from pathlib import Path
from prepare import HERE,SOURCE,patch
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
source=SOURCE.read_text();candidate=patch(source)
(out/'candidate.v').write_text(candidate)
# Both modified expressions belong to the combinational read/validity cone. Expose
# every CSR state bit as an arbitrary shared input, including unreachable states.
regs=re.findall(r'^    reg (\[[^\n]+?\] )?(\w+);$',source,re.M)
ports=['input [11:0] csr_addr','input read_enable']+['input '+width+name for width,name in regs]
constants=source[source.index('    // Common CSR addresses'):source.index('    // CSR registers')]
aliases=source[source.index('    wire [31:0] sstatus'):source.index('    wire cycle_enabled')]
valid=source[source.index('    // Check if CSR address is valid'):source.index('    // Initialize CSRs')]
for name,text in [('gold',source),('gate',candidate)]:
    read=text[text.index('    // Read logic'):text.rindex('endmodule')]
    (out/(name+'.v')).write_text('module '+name+'('+','.join(ports+['output reg [31:0] read_data','output csr_valid'])+');\n'+constants+aliases+valid+read+'endmodule\n')
names=['csr_addr','read_enable']+[name for width,name in regs]
connections=','.join('.'+name+'('+name+')' for name in names)
h='module equiv('+','.join(ports+['output same'])+');\nwire [31:0] gd,cd;wire gv,cv;\n'
h+='gold gold('+connections+',.read_data(gd),.csr_valid(gv));\n'
h+='gate gate('+connections+',.read_data(cd),.csr_valid(cv));\nassign same=(gd==cd)&&(gv==cv);\nendmodule\n'
(out/'harness.sv').write_text(h)
(out/'proof.ys').write_text(f'read_verilog {out/"gold.v"} {out/"gate.v"} {out/"harness.sv"}\nprep -top equiv; flatten; opt; check -assert; sat -prove same 1 -verify;\n')
with (out/'proof.log').open('w') as log:
    rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[Path(__file__),HERE/'prepare.py',SOURCE]+[out/name for name in ['candidate.v','gold.v','gate.v','harness.sv','proof.ys']]
(out/'results.json').write_text(json.dumps({'passed':rc==0,'claim':'Identical read_data and csr_valid for every CSR address, read enable, and arbitrary CSR state. Sequential logic is byte-identical.','sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if rc:raise SystemExit('FAIL CSR read proof')
print('PASS arbitrary-state CSR read/validity equivalence')
