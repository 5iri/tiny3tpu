#!/usr/bin/env python3
"""Flatten execution-result selection while preserving all execution outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("shared_mul", HERE.parent / "shared-mul/run.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def prepare(out):
    overlay = shared.prepare(out)
    path = overlay / "execution_unit.v"
    original = path.read_text()
    candidate, count = re.subn(r"^\s*exec_output = [^;]+;", "", original, flags=re.M)
    assert count == 8
    candidate = candidate.replace("output reg [31:0] exec_output", "output wire [31:0] exec_output")
    selection = """
// Decode independent result sources in parallel. The opcode terms are mutually
// exclusive, so a masked OR preserves the original priority logic exactly.
wire result_enable = !interrupt_pending && !(instr_valid && instr_id == INSTR_INVALID);
wire result_alu = result_enable && (opcode == 7'b0110011 || opcode == 7'b0010011);
wire result_link = result_enable && (opcode == 7'b1101111 || opcode == 7'b1100111);
wire result_lui = result_enable && opcode == 7'b0110111;
wire result_auipc = result_enable && opcode == 7'b0010111;
wire result_csr = result_enable && opcode == 7'b1110011 &&
    instr_id != INSTR_MRET && instr_id != INSTR_SRET && instr_id != INSTR_ECALL &&
    instr_id != INSTR_EBREAK && instr_id != INSTR_WFI && instr_id != INSTR_SFENCE_VMA &&
    csr_valid && !csr_read_only_violation && !csr_privilege_violation &&
    !csr_satp_tvm_violation && !csr_counter_access_violation;
assign exec_output = ({32{result_alu}} & alu_inst.ALUoutput) |
                     ({32{result_link}} & (pc_input + 32'd4)) |
                     ({32{result_lui}} & imm) |
                     ({32{result_auipc}} & (pc_input + imm)) |
                     ({32{result_csr}} & csr_rd_value);

"""
    candidate = candidate.replace("// For all R-type instructions", selection + "// For all R-type instructions", 1)
    path.write_text(candidate)
    (out / "execution_reference.v").write_text(original.replace("module execution_unit(", "module execution_reference("))
    return overlay


def prove(out, overlay, source):
    # A common unconstrained ALU result proves the surrounding selection for
    # every value, without asking a SAT solver to rediscover multiplication.
    header = (overlay / "execution_unit.v").read_text().split("// Internal signals")[0]
    ports = re.findall(r"(input|output)\s+(?:wire|reg)\s*(\[[^\]]+\])?\s*(\w+)", header)
    inputs = [(w, n) for direction, w, n in ports if direction == "input"]
    outputs = [(w, n) for direction, w, n in ports if direction == "output"]
    harness = "module result_select_equiv (\n" + ",\n".join("input wire " + w + " " + n for w, n in inputs)
    harness += ",\noutput wire same);\n"
    for label, module in (("gold", "execution_reference"), ("gate", "execution_unit")):
        harness += "\n".join("wire " + w + " " + label + "_" + n + ";" for w, n in outputs) + "\n"
        connections = ["." + n + "(" + n + ")" for w, n in inputs]
        connections += ["." + n + "(" + label + "_" + n + ")" for w, n in outputs]
        harness += module + " " + label + "(" + ",".join(connections) + ");\n"
    harness += "assign same = " + " && ".join("(gold_" + n + " == gate_" + n + ")" for w, n in outputs) + ";\nendmodule\n"
    stub = """module alu(input wire [31:0] div_result, rs1, rs2, imm, pc_input,
        input wire [6:0] instr_id, output wire [31:0] ALUoutput);
        assign ALUoutput = div_result;
    endmodule
"""
    (out / "harness.sv").write_text(harness)
    (out / "alu_abstract.v").write_text(stub)
    files = [out / "alu_abstract.v", source / "rtl/core_modules/csr_exec.v",
             out / "execution_reference.v", overlay / "execution_unit.v", out / "harness.sv"]
    script = "read_slang --top result_select_equiv -I" + str(source / "rtl/include") + " " + " ".join(map(str, files)) + "\n"
    script += "prep -top result_select_equiv; flatten; opt; check -assert; sat -prove same 1 -verify;\n"
    (out / "proof.ys").write_text(script)
    shared.retime.run(["/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys", "-Q", "-T", "-m", "slang",
                       "-s", out / "proof.ys"], out / "proof.log")
    print("PASS: all execution-unit outputs equivalent with an arbitrary common ALU result", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "prove", "verify", "synth", "route"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--synapse32-dir", type=Path, default=ROOT.parent / "synapse32")
    parser.add_argument("--seed", type=int, default=4)
    args = parser.parse_args()
    args.out = args.out.resolve(); args.synapse32_dir = args.synapse32_dir.resolve()
    out = args.out; source = args.synapse32_dir
    overlay = prepare(out)
    if args.mode == "prove":
        prove(out, overlay, source)
    elif args.mode == "verify":
        prove(out, overlay, source)
        shared.retime.verify(args, overlay)
        shared.retime.run([sys.executable, HERE.parent / "mul-pipeline/benchmark.py", "--out", out / "ipc",
                           "--baseline", ROOT / "build-ddr-shared-mul", "--candidate", out], out / "ipc.log")
        print((out / "ipc.log").read_text(), flush=True)
    elif args.mode == "synth":
        shared.retime.run([ROOT / ".venv-ddr-compat/bin/python", ROOT / "tools/kc705_open_build.py",
                           "synth", "--synapse32-dir", source, "--cpu-overlay-dir", overlay,
                           "--build-dir", out / "board"], out / "synth-console.log")
    elif args.mode == "route":
        board = out / "board"
        tool = Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx")
        chipdb = Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin")
        command = [tool, "--chipdb", chipdb, "--xdc", board / "kc705.xdc", "--freq", "100", "--seed", str(args.seed),
                   "--json", board / "soc.json", "--write", board / "routed.json", "--report", board / "report.json", "--log", board / "route.log"]
        paths = [tool, chipdb, board / "kc705.xdc", board / "soc.json", board / "firmware.hex", board / "synth.ys", Path(__file__)]
        paths += sorted(overlay.glob("*.v"))
        manifest = {"command": list(map(str, command)), "seed": args.seed,
                    "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
        (board / "route-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        with (board / "route-console.log").open("w") as log:
            rc = subprocess.run(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT).returncode
        sys.path.insert(0, str(ROOT))
        from tools.synapse32_timing_report import summarize
        manifest["timing"] = summarize((board / "route.log").read_text(), exit_code=rc)
        (board / "route-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps(manifest["timing"]["final_clocks"], indent=2), flush=True)
        if not manifest["timing"]["accepted"]:
            raise SystemExit("REJECTED: " + str(manifest["timing"]["reasons"]))
    paths = [Path(__file__), *sorted(overlay.glob("*.v")), *out.glob("*reference.v"), *out.glob("proof.*"), *out.glob("harness.sv")]
    (out / (args.mode + "-sources.json")).write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, indent=2) + "\n")


if __name__ == "__main__":
    main()
