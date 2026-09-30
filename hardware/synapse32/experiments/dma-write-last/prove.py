#!/usr/bin/env python3
"""Prove exact DMA write flag expressions, including zero and modular wrap."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import SOURCE,patch,START_NEW,STEP_OLD,STEP_NEW
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
(out/'axi_dma_wr.v').write_text(patch(SOURCE.read_text()))
# Copy the changed expressions, retaining the original assignment widths.
start_expr=START_NEW.split('output_last_cycle_next = ',1)[1].split(';',1)[0]
step_expr=STEP_NEW.split('output_last_cycle_next = ',1)[1].split(';',1)[0]
h=f'''module equiv #(parameter W=15)(input [15:0] tr_word_count_next,
input [W-1:0] output_cycle_count_reg,output same);
wire [14:0] initial_count=(tr_word_count_next-1)>>2;
wire [W-1:0] output_cycle_count_next=output_cycle_count_reg-1;
assign same=((initial_count==0)==({start_expr})) &&
            ((output_cycle_count_next==0)==({step_expr}));
endmodule
'''
(out/'harness.v').write_text(h);yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');results=[]
for width in [1,2,8,15,16,32,64]:
 script=out/f'proof-{width}.ys';script.write_text(f'read_verilog {out/"harness.v"}\nchparam -set W {width} equiv\nprep -top equiv; opt; check -assert; sat -prove same 1 -verify;\n')
 with (out/f'proof-{width}.log').open('w') as log:rc=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
 results.append(dict(width=width,passed=rc==0))
paths=[SOURCE,out/'axi_dma_wr.v',out/'harness.v',yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]+list(out.glob('proof-*.ys'))
r=dict(passed=all(v['passed'] for v in results),widths=results,claim='Initial flag equality for all 16-bit transfer counts in the guarded aligned 32-bit profile; decrement flag equality for every counter value at each tested width. No nonzero-length or reachable-state assumption. Other initial profiles retain the original expression; count updates and other RTL bytes are unchanged.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS DMA write initial and decrement last-cycle flags, including zero and wrap')
