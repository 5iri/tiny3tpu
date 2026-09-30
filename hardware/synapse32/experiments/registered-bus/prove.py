#!/usr/bin/env python3
"""Prove cycle-accurate sequencer equivalence at its ready/valid interface.

Request payload is compared whenever a request is offered (including stalls).
Payload outside req_valid is intentionally unspecified. All CPU-side outputs,
valid/ready controls, and faults are compared on every cycle. No traffic input
assumptions or added latency are used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from prepare import prepare,ROOT

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out",type=Path,required=True)
parser.add_argument("--candidate",type=Path)
args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
candidate=args.candidate.resolve() if args.candidate else prepare(out)
original=ROOT/"hardware/synapse32/synapse32_memory_sequencer.sv"
for name,path in (("gold",original),("gate",candidate)):
    source=path.read_text().replace("module synapse32_memory_sequencer #(","module "+name+" #(")
    source=source.replace("    input  logic        clk,","    output wire [41:0] proof_state,\n    input  logic        clk,")
    source=source.replace("    always_ff @(posedge clk) begin","    assign proof_state = {state, fetch_addr, load_offset, load_type_latched, step_pending};\n\n    always_ff @(posedge clk) begin")
    (out/(name+".sv")).write_text(source)
inputs={"clk":1,"rst":1,"ready_to_run":1,"cpu_pc":32,"cpu_rd_en":1,"cpu_wr_en":1,
        "cpu_rd_addr":32,"cpu_wr_addr":32,"cpu_wdata":32,"cpu_wstrb":4,"cpu_load_type":3,
        "req_ready":1,"resp_valid":1,"resp_rdata":32,"resp_error":1}
outputs={"cpu_instr":32,"cpu_rdata":32,"cpu_step":1,"fault":1,"req_valid":1,
         "req_write":1,"req_addr":32,"req_wdata":32,"req_wstrb":4,"resp_ready":1,"proof_state":42}
def width(n):return "" if n==1 else f"[{n-1}:0] "
harness="module sequencer_equiv (\n"+",\n".join("input wire "+width(n)+p for p,n in inputs.items())+",\noutput wire same\n);\n"
for name in ("gold","gate"):
    harness += "\n".join("wire "+width(n)+name+"_"+p+";" for p,n in outputs.items())+"\n"
    harness += name+" dut_"+name+"("+",".join("."+p+"("+p+")" for p in inputs)+","+",".join("."+p+"("+name+"_"+p+")" for p in outputs)+");\n"
payload=["req_write","req_addr","req_wdata","req_wstrb"]
checks=[f"gold_{p} == gate_{p}" for p in outputs if p not in payload]
checks += ["(!gold_req_valid || ("+" && ".join(f"gold_{p} == gate_{p}" for p in payload)+"))"]
harness+="assign same = "+" && ".join("("+c+")" for c in checks)+";\nendmodule\n"
(out/"harness.sv").write_text(harness)
script="read_verilog -sv {} {} {};\n".format(out/"gold.sv",out/"gate.sv",out/"harness.sv")
script+="""hierarchy -check -top sequencer_equiv; proc; flatten; opt; check -assert;
sat -seq 4 -tempinduct -maxsteps 16 -set-init-zero -prove same 1 -verify;
"""
(out/"proof.ys").write_text(script)
with (out/"proof.log").open("w") as log:
    subprocess.run(["/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys","-Q","-T","-s",str(out/"proof.ys")],stdout=log,stderr=subprocess.STDOUT,check=True)
paths=[original,candidate,out/"harness.sv",out/"proof.ys",Path(__file__)]
(out/"proof-sources.json").write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+"\n")
print("PASS: cycle-accurate sequencer protocol equivalence")
