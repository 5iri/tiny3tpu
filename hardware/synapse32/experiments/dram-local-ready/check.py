#!/usr/bin/env python3
"""Prove complete eight-bank command chooser and run upstream multiplexer tests."""
import argparse,hashlib,json,re,subprocess,sys,unittest
from pathlib import Path
from migen.fhdl import verilog
from litex.soc.interconnect import stream
from litedram.common import cmd_request_rw_layout
import litedram.core.multiplexer as multiplexer
from generate import patch_multiplexer
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--upstream',type=Path,required=True)
a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)

def emit(label):
    requests=[stream.Endpoint(cmd_request_rw_layout(a=14,ba=3),name=f'bank{i}') for i in range(8)]
    dut=multiplexer._CommandChooser(requests)
    ios=set(dut.cmd.flatten()+[dut.want_reads,dut.want_writes,dut.want_cmds,dut.want_activates])
    for req in requests: ios.update(req.flatten())
    (out/f'{label}.v').write_text(str(verilog.convert(dut,ios=ios,name=label)))
emit('gold');patch_multiplexer(out/'evidence');emit('gate')
ports=re.findall(r'^\s*(input|output)\s+(?:reg\s+)?(\[[^\]]+\]\s+)?(\w+)[,\n]',(out/'gold.v').read_text(),re.M)
inputs=[(w or '',n) for d,w,n in ports if d=='input'];outputs=[(w or '',n) for d,w,n in ports if d=='output']
assert inputs and outputs
h='module equiv('+','.join('input wire '+w+n for w,n in inputs)+',output wire same);\n'
for label in ['gold','gate']:
    h+='\n'.join('wire '+w+label+'_'+n+';' for w,n in outputs)+'\n'
    h+=label+' '+label+'('+','.join('.'+n+'('+n+')' for w,n in inputs)+','+','.join('.'+n+'('+label+'_'+n+')' for w,n in outputs)+');\n'
# Strengthen induction with unchanged arbitration state equality.
h+='assign same=(gold.grant==gate.grant) && '+' && '.join('(gold_'+n+'==gate_'+n+')' for w,n in outputs)+';\nendmodule\n'
(out/'harness.v').write_text(h)
script=f'read_slang --top equiv {out/"gold.v"} {out/"gate.v"} {out/"harness.v"}\nprep -top equiv; flatten; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -set-init-zero -prove same 1 -verify;\n'
(out/'proof.ys').write_text(script)
with (out/'proof.log').open('w') as log:
    proof=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-m','slang','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT)
sys.path.insert(0,str(a.upstream.resolve()))
from test import test_multiplexer
with (out/'tests.log').open('w') as log:
    tests=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_multiplexer))
paths=[Path(__file__),Path(__file__).with_name('generate.py'),Path(test_multiplexer.__file__),out/'gold.v',out/'gate.v',out/'harness.v',out/'proof.ys']
paths += [Path(x) for x in json.loads((out/'evidence/sources.json').read_text())]
passed=proof.returncode==0 and tests.wasSuccessful()
(out/'results.json').write_text(json.dumps({'passed':passed,'equivalence':proof.returncode==0,'tests':tests.testsRun,'claim':'All eight-bank command chooser outputs identical on every cycle under arbitrary request/filter/ready/reset inputs.','sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if not passed: raise SystemExit('FAIL: inspect '+str(out))
print('PASS chooser equivalence and',tests.testsRun,'upstream multiplexer tests')
