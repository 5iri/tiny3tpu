#!/usr/bin/env python3
"""Check state recoding on the actual board-geometry bank machine."""
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path
from migen.fhdl import verilog
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--upstream',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(a.upstream.resolve()))
from test import test_bankmachine
from litedram.modules import MT8JTF12864
memory=MT8JTF12864(100e6,'1:4')
dut=test_bankmachine.BankMachineDUT(0,phy_settings={'nphases':4,'cwl':5,'memtype':'DDR3','dfi_databits':128},geom_settings={n:getattr(memory.geom_settings,n) for n in ['rowbits','colbits','bankbits']},timing_settings={n:getattr(memory.timing_settings,n) for n in ['tRP','tRCD','tWR','tCCD','tRC','tRAS']})
bank=dut.bankmachine
s=str(verilog.convert(dut,ios=set(bank.req.flatten()+bank.cmd.flatten()+[bank.refresh_req,bank.refresh_gnt]),name='bank'))
s,count=re.subn(r'^(reg\s+\[[^\]]+\]\s+state\s*=)',r'(* fsm_encoding="one-hot" *) \1',s,flags=re.M);assert count==1,count
(out/'bank.v').write_text(s)
script=f'read_verilog {out/"bank.v"}\nprep -top bank; memory_map; opt; equiv_opt -assert -async2sync fsm;\n'
(out/'proof.ys').write_text(script)
with (out/'proof.log').open('w') as log:
 rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
if 'Recoding FSM' not in (out/'proof.log').read_text(): rc=1
paths=[Path(__file__),Path(test_bankmachine.__file__),out/'bank.v',out/'proof.ys']
(out/'results.json').write_text(json.dumps({'passed':rc==0,'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if rc:raise SystemExit('FAIL bank-machine recoding proof')
print('PASS bank-machine FSM recoding equivalence')
