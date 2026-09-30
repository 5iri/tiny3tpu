#!/usr/bin/env python3
"""Prove the retimed selector invariant against the actual pipeline registers.

This is a control proof, not full-CPU ISA or physical timing certification.
All input tags, instruction IDs, reset, hold, flush, and faults are unrestricted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PLAN = HERE.parent / "pipeline-plan"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--synapse32-dir", type=Path, default=ROOT.parent / "synapse32")
parser.add_argument("--yosys", default="/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys")
args = parser.parse_args()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
tb = (PLAN / "forward_lookahead_tb.sv").read_text()
# Keep the actual reference-stage wiring used in the dynamic test.
connections = tb[tb.index("    ID_EX ex_reg ("):tb.index("    task tick;")]
declarations = tb[tb.index("    wire [4:0] ex_rs1"):tb.index("    integer checks")]
harness = """module forwarding_invariant (
    input wire clk, rst, flush, hold, stall, ex_mem_flush, mem_page_fault,
    input wire [4:0] id_rs1, id_rs2, id_rd,
    input wire id_rs1_valid, id_rs2_valid, id_rd_valid,
    input wire [6:0] id_instr,
    output wire same
);
""" + declarations + connections + """
    assign same = {gold_a, gold_b} == {got_a, got_b};
endmodule
"""
# Prove the helper actually embedded in the materialized CPU overlay.
cpu = (out / "overlay/riscv_cpu.v").read_text()
helper = '`include "instr_defines.vh"\n' + cpu[cpu.index("module synapse32_forward_lookahead ("):]
helper = helper.replace("module synapse32_forward_lookahead (", "module forward_lookahead (")
(out / "proof-helper.sv").write_text(helper)
(out / "proof-harness.sv").write_text(harness)
sources = [args.synapse32_dir / "rtl/pipeline_stages" / (n + ".v")
           for n in ("ID_EX", "EX_MEM", "MEM_WB", "forwarding_unit")]
sources += [out / "proof-helper.sv", out / "proof-harness.sv"]
script = "read_verilog -sv -I{} {};\n".format(
    args.synapse32_dir / "rtl/include", " ".join(map(str, sources)))
script += """hierarchy -check -top forwarding_invariant;
proc; flatten; opt; check -assert;
async2sync; opt;
sat -seq 3 -tempinduct -set-init-zero -prove same 1 -verify;
"""
(out / "proof.ys").write_text(script)
with (out / "proof.log").open("w") as log:
    subprocess.run([args.yosys, "-Q", "-T", "-s", str(out / "proof.ys")],
                   stdout=log, stderr=subprocess.STDOUT, check=True)
sources += [out / "overlay/riscv_cpu.v", out / "proof.ys", Path(__file__),
            args.synapse32_dir / "rtl/include/instr_defines.vh"]
manifest = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
(out / "proof-sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("PASS: inductive selector invariant; see", out / "proof.log")
