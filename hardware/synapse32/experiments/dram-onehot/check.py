#!/usr/bin/env python3
"""Check bank command equivalence and the upstream bank-machine tests."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import unittest
from generate import patch_fsms, lower_onehot_cases

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--upstream",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
parser.add_argument("--board-settings",action="store_true",help="Prove with KC705 DDR3 geometry and 100 MHz timing settings")
args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(args.upstream.resolve()))
from test import test_bankmachine
from migen.fhdl import verilog


def emit(label):
    options={}
    if args.board_settings:
        from litedram.modules import MT8JTF12864
        module=MT8JTF12864(100e6,"1:4")
        options={"phy_settings":{"nphases":4,"cwl":5,"memtype":"DDR3","dfi_databits":128},
                 "geom_settings":{n:getattr(module.geom_settings,n) for n in ("rowbits","colbits","bankbits")},
                 "timing_settings":{n:getattr(module.timing_settings,n) for n in ("tRP","tRCD","tWR","tCCD","tRC","tRAS")}}
    dut=test_bankmachine.BankMachineDUT(0,**options)
    bank=dut.bankmachine
    ios=set(bank.req.flatten()+bank.cmd.flatten()+[bank.refresh_req,bank.refresh_gnt])
    bank.fsm.finalize()
    bank.fsm.state.name_override="fsm_state"
    bank.fsm.next_state.name_override="fsm_next_state"
    global state_count
    state_count=len(bank.fsm.actions)
    text=verilog.convert(dut,ios=ios,name=label)
    text=str(text)
    if label=="gate": text=lower_onehot_cases(text,["fsm_state"])
    (out/(label+".v")).write_text(text)


emit("gold")
patch_fsms(out/"evidence")
import litedram.core.bankmachine as bankmachine
test_bankmachine.BankMachine=bankmachine.BankMachine
emit("gate")
gold=(out/"gold.v").read_text();gate=(out/"gate.v").read_text()
ports=re.findall(r"^\s*(input|output)\s+(?:reg\s+)?(\[[^\]]+\]\s+)?(\w+)[,\n]",gold,re.M)
inputs=[(w or "",n) for direction,w,n in ports if direction=="input"]
outputs=[(w or "",n) for direction,w,n in ports if direction=="output"]
harness="module bank_equiv("+",".join("input wire "+w+n for w,n in inputs)+",output wire same);\n"
for instance in ("gold","gate"):
    harness+="\n".join("wire "+w+instance+"_"+n+";" for w,n in outputs)+"\n"
    harness+=instance+" "+instance+"("+",".join("."+n+"("+n+")" for w,n in inputs)+","+",".join("."+n+"("+instance+"_"+n+")" for w,n in outputs)+");\n"
checks=[f"gold_{n}==gate_{n}" for w,n in outputs]
registers=re.findall(r"\breg\s+(?:\[[^\]]+\]\s+)?(\w+)\s*=\s*[^;]+;",gold)
for n in registers:
    if n in ("fsm_state","fsm_next_state"): continue
    assert re.search(r"\breg\s+(?:\[[^\]]+\]\s+)?"+n+r"\s*=",gate)
    checks.append(f"gold.{n}==gate.{n}")
for name,low,high in re.findall(r"\breg\s+\[[^\]]+\]\s+(\w+)\[(\d+):(\d+)\];",gold):
    checks += [f"gold.{name}[{i}]==gate.{name}[{i}]" for i in range(int(low),int(high)+1)]
checks.append("("+" || ".join(f"(gold.fsm_state=={i} && gate.fsm_state=={1<<i})" for i in range(state_count))+")")
harness+="assign same="+" && ".join("("+c+")" for c in checks)+";\nendmodule\n"
(out/"harness.sv").write_text(harness)
script=f"read_slang --top bank_equiv {out/'gold.v'} {out/'gate.v'} {out/'harness.sv'}\n"
script+="prep -top bank_equiv; flatten; memory_map; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 16 -set-init-zero -prove same 1 -verify;\n"
(out/"proof.ys").write_text(script)
with (out/"proof.log").open("w") as log:
    proof=subprocess.run(["/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys","-Q","-T","-m","slang","-s",str(out/"proof.ys")],stdout=log,stderr=subprocess.STDOUT)
with (out/"tests.log").open("w") as log:
    tests=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_bankmachine))
paths=[Path(__file__),Path(__file__).with_name("generate.py"),Path(test_bankmachine.__file__),out/"gold.v",out/"gate.v",out/"harness.sv",out/"proof.ys"]
paths += [Path(p) for p in json.loads((out/"evidence/sources.json").read_text())]
passed=proof.returncode==0 and tests.wasSuccessful()
(out/"results.json").write_text(json.dumps({"passed":passed,"equivalence":proof.returncode==0,"board_settings":args.board_settings,"tests":tests.testsRun,"state_count":state_count,"sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+"\n")
if not passed: raise SystemExit("Explicit one-hot bank validation failed; inspect "+str(out))
print("PASS explicit one-hot bank equivalence and",tests.testsRun,"upstream tests")
