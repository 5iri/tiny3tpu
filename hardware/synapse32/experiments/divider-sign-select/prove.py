#!/usr/bin/env python3
"""Prove final signed divide selection and full module sequential equivalence."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import OLD,NEW,prepare
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();source=a.source.resolve();out=a.out.resolve();overlay=prepare(source,out)
root=Path(__file__).resolve().parents[4];yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
body=f'''read_verilog {source/'divider.v'}
rename divider gold
read_verilog {overlay/'divider.v'}
rename divider gate
proc
async2sync
opt
equiv_make gold gate equiv
hierarchy -top equiv
opt_clean
equiv_simple
equiv_induct -seq 4
equiv_status -assert
'''
(out/'proof.ys').write_text(body)
with (out/'proof.log').open('w') as log:rc=subprocess.run([str(yosys),'-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
commands=[['iverilog','-g2012','-s','divider_tb','-o',str(out/'unit.vvp'),str(overlay/'divider.v'),str(root/'hardware/synapse32/experiments/divider/divider_tb.sv')],['vvp',str(out/'unit.vvp')]]
for name,command in zip(['unit-compile','unit'],commands):
 with (out/(name+'.log')).open('w') as log:rc |= subprocess.run(command,stdout=log,stderr=subprocess.STDOUT).returncode
paths=list(source.glob('*.v'))+list(overlay.glob('*.v'))+[out/f for f in ['proof.ys','proof.log','unit-compile.log','unit.log']]+[yosys,root/'hardware/synapse32/experiments/divider/divider_tb.sv',Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]
r=dict(passed=rc==0,claim='Full divider sequential equivalence including busy, done, result and all original working registers. Signed alternatives change only combinational final selection. No iteration, launch, reset, cancel, exception or completion edge changes. Unit test checks arithmetic and exact latency including cancellation boundaries.',commands=commands,sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS whole divider equivalence and exact-latency arithmetic/cancel suite')
