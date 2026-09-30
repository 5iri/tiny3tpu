#!/usr/bin/env python3
"""Share the combinational RV32 multiply datapath without changing CPU cycles."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("retime", HERE.parent / "forward-retime/run.py")
retime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retime)


def prepare(out):
    overlay = retime.prepare(out)
    path = overlay / "alu.v"
    original = path.read_text()
    start = original.index("wire signed [31:0] rs1_signed")
    end = original.index("wire div_by_zero", start)
    replacement = """// One signed 33-bit product covers all RV32 multiply variants. The
// extension bit selects signedness; low 32 bits are independent of it.
wire a_negative = rs1[31] && (instr_id == INSTR_MULH || instr_id == INSTR_MULHSU);
wire b_negative = rs2[31] && instr_id == INSTR_MULH;
wire signed [32:0] mul_a = $signed({a_negative, rs1});
wire signed [32:0] mul_b = $signed({b_negative, rs2});
wire signed [65:0] mul_product = mul_a * mul_b;
"""
    candidate = original[:start] + replacement + original[end:]
    for old in ("mul_signed", "mul_mixed", "mul_unsigned"):
        candidate = candidate.replace(old + "[", "mul_product[")
    path.write_text(candidate)
    (out / "alu_reference.v").write_text(original.replace("module alu (", "module alu_reference ("))
    return overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify", "synth", "route"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--synapse32-dir", type=Path, default=ROOT.parent / "synapse32")
    parser.add_argument("--seed", type=int, default=4)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.synapse32_dir = args.synapse32_dir.resolve()
    out = args.out
    overlay = prepare(out)
    paths = sorted(overlay.glob("*.v")) + [Path(__file__), HERE / "alu_tb.sv"]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out / (args.mode + "-sources.json")).write_text(json.dumps(hashes, indent=2) + "\n")
    if args.mode == "verify":
        retime.run(["iverilog", "-g2012", "-s", "shared_mul_alu_tb",
                    "-I" + str(args.synapse32_dir / "rtl/include"), "-o", out / "alu.vvp",
                    overlay / "alu.v", out / "alu_reference.v", HERE / "alu_tb.sv"],
                   out / "alu-compile.log")
        retime.run(["vvp", out / "alu.vvp"], out / "alu.log")
        print((out / "alu.log").read_text(), flush=True)
        retime.verify(args, overlay)
        retime.run([sys.executable, HERE.parent / "mul-pipeline/benchmark.py", "--out", out / "ipc",
                    "--baseline", ROOT / "build-ddr-retime", "--candidate", out], out / "ipc.log")
        print((out / "ipc.log").read_text(), flush=True)
    elif args.mode == "synth":
        retime.run([ROOT / ".venv-ddr-compat/bin/python", ROOT / "tools/kc705_open_build.py",
                    "synth", "--synapse32-dir", args.synapse32_dir,
                    "--cpu-overlay-dir", overlay, "--build-dir", out / "board"], out / "synth-console.log")
    elif args.mode == "route":
        board = out / "board"
        tool = Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx")
        chipdb = Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin")
        command = [tool, "--chipdb", chipdb, "--xdc", board / "kc705.xdc", "--freq", "100",
                   "--seed", str(args.seed), "--json", board / "soc.json", "--write", board / "routed.json",
                   "--report", board / "report.json", "--log", board / "route.log"]
        paths += [tool, chipdb, board / "kc705.xdc", board / "soc.json", board / "synth.ys", board / "firmware.hex"]
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
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())


if __name__ == "__main__":
    main()
