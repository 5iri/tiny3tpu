#!/usr/bin/env python3
"""Prove PE outputs cycle-equivalent, including reset, clear and overflow."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import SOURCE,GOLDEN,prepare
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();prepare(out)
(out/'gold.v').write_text(GOLDEN.read_text().replace('module pe #(','module gold #('))
(out/'gate.v').write_text((out/'pe.v').read_text().replace('module pe #(','module gate #('))
(out/'harness.v').write_text('''module equiv(input clk,rst,clear,input signed [7:0] a_in,b_in,output same);
wire signed [7:0] ga,gb,ca,cb; wire signed [31:0] gc,cc;
gold g(.clk(clk),.rst(rst),.clear(clear),.a_in(a_in),.b_in(b_in),.a_out(ga),.b_out(gb),.c(gc));
gate c(.clk(clk),.rst(rst),.clear(clear),.a_in(a_in),.b_in(b_in),.a_out(ca),.b_out(cb),.c(cc));
assign same=(ga==ca)&&(gb==cb)&&(gc==cc);
endmodule
''')
(out/'proof.ys').write_text(f'read_slang --top equiv {out/"gold.v"} {out/"gate.v"} {out/"harness.v"}\nprep -top equiv; flatten; opt; async2sync; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -set-init-zero -set-at 1 rst 1 -prove same 1 -verify;\n')
with (out/'proof.log').open('w') as f:rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-m','slang','-s',str(out/'proof.ys')],stdout=f,stderr=subprocess.STDOUT).returncode
paths=[SOURCE,GOLDEN,Path(__file__),Path(__file__).with_name('prepare.py'),out/'pe.v',out/'gold.v',out/'gate.v',out/'harness.v',out/'proof.ys']
(out/'results.json').write_text(json.dumps({'passed':rc==0,'claim':'PE DW=8 CW=32 output equivalence for arbitrary signed inputs, clear and reset after reset initialization, including overflow. No extra MAC cycle.','sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if rc:raise SystemExit('PE equivalence failed')
print('PASS PE cycle equivalence')
