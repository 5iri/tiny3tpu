#!/usr/bin/env python3
"""Prove the changed decision without state/reachability/transfer assumptions."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import SOURCE,patch,OLD,NEW
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
original=SOURCE.read_text();candidate=patch(original)
assert candidate.replace(NEW,OLD)==original
(out/'axi_dma_rd.v').write_text(candidate)
h='''module equiv #(parameter W=16)(input [W-1:0] op_word_count_reg,tr_word_count_next,output same);
wire [W-1:0] op_word_count_next=op_word_count_reg-tr_word_count_next;
assign same=(op_word_count_next>0)==(op_word_count_reg!=tr_word_count_next);
endmodule
'''
(out/'harness.v').write_text(h)
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');results=[]
for width in [1,2,8,12,16,32,64]:
    script=out/f'proof-{width}.ys';script.write_text(f'read_verilog {out/"harness.v"}\nchparam -set W {width} equiv\nprep -top equiv; opt; check -assert; sat -prove same 1 -verify;\n')
    with (out/f'proof-{width}.log').open('w') as log:rc=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
    results.append(dict(width=width,passed=rc==0))
paths=[SOURCE,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve(),yosys,out/'harness.v',out/'axi_dma_rd.v']+list(out.glob('proof-*.ys'))
r=dict(passed=all(x['passed'] for x in results),widths=results,claim='Exact unsigned decision equality, including modular underflow, without aligned-address, length, handshake or reachable-state assumptions. Only this decision changes in the module.',sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n')
assert r['passed'];print('PASS DMA read decision equivalence at widths 1,2,8,12,16,32,64')
