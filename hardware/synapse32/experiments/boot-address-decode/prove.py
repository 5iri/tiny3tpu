#!/usr/bin/env python3
"""Prove boot decode equality at every address and signed 32-bit size."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from prepare import OLD, NEW, patch
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--soc',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
source=a.soc.resolve();(out/'candidate.sv').write_text(patch(source.read_text()))
h='module equiv(input [31:0] req_addr,input signed [31:0] BOOT_WORDS,output same);\n'
h+=OLD.replace('boot_address','gold')+'\n'+NEW.replace('boot_address','gate')+'\nassign same=gold==gate;\nendmodule\n'
(out/'harness.v').write_text(h);script=out/'proof.ys'
script.write_text(f'read_verilog {out/"harness.v"}\nprep -top equiv; opt; check -assert; sat -prove same 1 -verify;\n')
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
with (out/'proof.log').open('w') as log:rc=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[source,out/'candidate.sv',out/'harness.v',script,yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]
r=dict(passed=rc==0,claim='Exact boot decode equality for all request addresses and signed 32-bit BOOT_WORDS. Other sizes use the original expression. Only the combinational decode changes.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS boot decode for all addresses and signed 32-bit sizes')
