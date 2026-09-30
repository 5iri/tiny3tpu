#!/usr/bin/env python3
"""Inductively prove UART outputs and ownership of all valid FIFO bytes."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from prepare import prepare,ROOT

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",type=Path,required=True)
out=parser.parse_args().out.resolve();candidate=prepare(out)
inputs={"clk":1,"rst":1,"addr":32,"write_data":32,"write_enable":1,"read_enable":1,"rx":1}
outputs={"read_data":32,"uart_valid":1,"interrupt":1,"tx":1}
def width(n):return "" if n==1 else f"[{n-1}:0] "
harness="module uart_equiv("+",".join("input wire "+width(n)+p for p,n in inputs.items())+",output wire same);\n"
for name,module in (("gold","uart_reference"),("gate","uart")):
    harness+="\n".join("wire "+width(n)+name+"_"+p+";" for p,n in outputs.items())+"\n"
    harness+=module+" "+name+"("+",".join("."+p+"("+p+")" for p in inputs)+","+",".join("."+p+"("+name+"_"+p+")" for p in outputs)+");\n"
state="lcr ier fcr scr dll dlh tx_data tx_busy tx_start_pending tx_state tx_bit_count tx_out baud_counter baud_div tx_fifo_head tx_fifo_tail tx_fifo_count rx_state rx_shift rx_bit_count rx_baud_counter rx_prev rbr rx_oe rx_fifo_head rx_fifo_tail rx_fifo_count thre_irq tx_thre_prev".split()
checks=[f"gold_{p}==gate_{p}" for p in outputs]
checks += [f"gold.{p}==gate.{p}" for p in state]
checks += [f"gold.rx_fifo[{i}]==gate.rx_fifo[{i}]" for i in range(16)]
harness+="wire [3:0] expected_tail=gold.tx_fifo_head+gold.tx_fifo_count[3:0];\n"
checks += ["gold.tx_fifo_count<=16","expected_tail==gold.tx_fifo_tail"]
for i in range(16):
    harness+=f"wire [3:0] offset_{i}=4'd{i}-gold.tx_fifo_head;\n"
    checks.append(f"offset_{i}>=gold.tx_fifo_count || gold.tx_fifo[{i}]==gate.tx_fifo[{i}]")
harness+="assign same="+" && ".join("("+c+")" for c in checks)+";\nendmodule\n"
(out/"harness.sv").write_text(harness)
source=ROOT.parent/"synapse32"
script="read_slang --top uart_equiv -I"+str(source/"rtl/include")+" "+str(out/"uart_reference.v")+" "+str(candidate)+" "+str(out/"harness.sv")+"\n"
script+="prep -top uart_equiv; flatten; memory_map; async2sync; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 16 -set-init-zero -prove same 1 -verify;\n"
(out/"proof.ys").write_text(script)
with (out/"proof.log").open("w") as log:
    result=subprocess.run(["/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys","-Q","-T","-m","slang","-s",str(out/"proof.ys")],stdout=log,stderr=subprocess.STDOUT)
paths=[candidate,out/"uart_reference.v",out/"harness.sv",out/"proof.ys",Path(__file__),Path(__file__).with_name("prepare.py")]
(out/"results.json").write_text(json.dumps({"passed":result.returncode==0,"sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if result.returncode:raise SystemExit("UART proof failed; see "+str(out/"proof.log"))
print("PASS UART outputs and valid FIFO bytes equivalent under arbitrary bus/RX/reset input")
