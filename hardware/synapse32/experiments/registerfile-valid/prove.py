#!/usr/bin/env python3
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import HERE,SOURCE,patch
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
(out/'gold.v').write_text(SOURCE.read_text().replace('module registerfile','module gold'))
(out/'gate.v').write_text(patch(SOURCE.read_text()).replace('module registerfile','module gate'))
h='''module equiv(input clk,rst,input [4:0] rs1,rs2,rd,input rs1_valid,rs2_valid,wr_en,input [31:0] rd_value,output same);
wire [31:0] g1,g2,c1,c2;
gold gold(.clk(clk),.rst(rst),.rs1(rs1),.rs2(rs2),.rd(rd),.rs1_valid(rs1_valid),.rs2_valid(rs2_valid),.wr_en(wr_en),.rd_value(rd_value),.rs1_value(g1),.rs2_value(g2));
gate gate(.clk(clk),.rst(rst),.rs1(rs1),.rs2(rs2),.rd(rd),.rs1_valid(rs1_valid),.rs2_valid(rs2_valid),.wr_en(wr_en),.rd_value(rd_value),.rs1_value(c1),.rs2_value(c2));
'''
checks=['g1==c1','g2==c2']+[f"gold.register_file[{i}] == (gate.written[{i}] ? gate.register_file[{i}] : 32'b0)" for i in range(32)]
h+='assign same='+' && '.join('('+c+')' for c in checks)+';\nendmodule\n';(out/'harness.sv').write_text(h)
s=f'read_slang --top equiv {out/"gold.v"} {out/"gate.v"} {out/"harness.sv"}\nprep -top equiv; flatten; memory_map; opt; async2sync; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -set-init-zero -prove same 1 -verify;\n';(out/'proof.ys').write_text(s)
with (out/'proof.log').open('w') as log:
 rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-m','slang','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[Path(__file__),HERE/'prepare.py',SOURCE,out/'gold.v',out/'gate.v',out/'harness.sv',out/'proof.ys']
(out/'results.json').write_text(json.dumps({'passed':rc==0,'claim':'Both read ports and architectural register contents equivalent for arbitrary addresses, read validity, write data/enables and resets, including write-through forwarding and x0.','sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if rc:raise SystemExit('FAIL register-file ownership proof')
print('PASS register-file ownership/read-output equivalence')
