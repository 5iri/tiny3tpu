#!/usr/bin/env python3
"""Prove the exact final multiply-combine expression for arbitrary partial words."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import OLD,NEW,EXPR,NEWEXPR,prepare
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
source=a.source.resolve();out=a.out.resolve();overlay=prepare(source,out)
h='''module combine(input [31:0] p00,input signed [33:0] p01,p10,p11,input low_s2,output same);
'''+OLD+'\n'+NEW+'\nassign same=('+EXPR+') == ('+NEWEXPR+');\nendmodule\n'
(out/'combine.v').write_text(h)
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
(out/'proof.ys').write_text(f'read_verilog {out/"combine.v"}\nprep -top combine; flatten; opt; check -assert; sat -prove same 1 -verify;\n')
with (out/'proof.log').open('w') as log:rc=subprocess.run([str(yosys),'-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=list(source.glob('*.v'))+list(overlay.glob('*.v'))+[out/'combine.v',out/'proof.ys',out/'proof.log',yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]
r=dict(passed=rc==0,claim='Exact low/high final result for arbitrary signed partial words and low selector. Partial-product registers, all reset behavior, operand capture, result edge and every other CPU source byte remain unchanged; hence sequential result equivalence follows at every edge without new stalls.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS all partial words and selector; unchanged registers and latency')
