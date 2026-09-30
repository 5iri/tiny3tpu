#!/usr/bin/env python3
"""Cascade-free RV32 multiply datapath without changing CPU cycles.

Composes the forwarding-retime overlay and replaces the ALU's three 64x64
products (which Yosys chains into deep DSP-cascade paths) with one 33x33
product split into four single-DSP 18x18 partials combined in fabric.
MUL stays single-cycle combinational; instruction latency and stalls are
unchanged. Production RTL and upstream Synapse32 are not modified.
"""
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
    replacement = """// Split 33x33 signed multiply into four single-DSP 18x18 partials with a
// fabric combine. Each partial fits one DSP48E1 25x18 multiplier, so there is
// no ACOUT/ACIN or P cascade on the MUL path; the remaining multiply delay is
// LUT/adder depth only. The extension bits select MULH/MULHSU signedness, the
// same rule as the shared-multiplier experiment. The exact 64-bit product is
// mul_product[63:0]; bits [65:64] are sign copies. MUL uses the low word.
wire ma_negative = rs1[31] && (instr_id == INSTR_MULH || instr_id == INSTR_MULHSU);
wire mb_negative = rs2[31] && instr_id == INSTR_MULH;
wire signed [32:0] ma_full = $signed({ma_negative, rs1});
wire signed [32:0] mb_full = $signed({mb_negative, rs2});
wire signed [17:0] ma_lo = $signed({1'b0, ma_full[16:0]});
wire signed [17:0] ma_hi = $signed({{2{ma_full[32]}}, ma_full[32:17]});
wire signed [17:0] mb_lo = $signed({1'b0, mb_full[16:0]});
wire signed [17:0] mb_hi = $signed({{2{mb_full[32]}}, mb_full[32:17]});
(* use_dsp = "yes" *) wire signed [35:0] pp_ll = ma_lo * mb_lo;
(* use_dsp = "yes" *) wire signed [35:0] pp_lh = ma_lo * mb_hi;
(* use_dsp = "yes" *) wire signed [35:0] pp_hl = ma_hi * mb_lo;
(* use_dsp = "yes" *) wire signed [35:0] pp_hh = ma_hi * mb_hi;
wire signed [65:0] mul_product = $signed({{30{pp_ll[35]}}, pp_ll})
    + ($signed({{30{pp_lh[35]}}, pp_lh}) <<< 17)
    + ($signed({{30{pp_hl[35]}}, pp_hl}) <<< 17)
    + ($signed({{30{pp_hh[35]}}, pp_hh}) <<< 34);
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
    parser.add_argument("--nextpnr", type=Path,
                        default=Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx"))
    parser.add_argument("--chipdb", type=Path,
                        default=Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin"))
    parser.add_argument("--seed", type=int, default=4)
    parser.add_argument("--ipc-baseline", type=Path, default=ROOT / "build-ddr-retime")
    parser.add_argument("--allow-const-holdouts", action="store_true",
                        help="Pass NEXTPNR_ALLOW_CONST_HOLDOUTS=1 for timing "
                             "diagnostics only; output stays rejected for bitstream use")
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.synapse32_dir = args.synapse32_dir.resolve()
    out = args.out
    overlay = prepare(out)
    paths = sorted(overlay.glob("*.v")) + [Path(__file__), HERE / "alu_tb.sv"]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out / (args.mode + "-sources.json")).write_text(json.dumps(hashes, indent=2) + "\n")
    if args.mode == "verify":
        retime.run(["iverilog", "-g2012", "-s", "split_mul_alu_tb",
                    "-I" + str(args.synapse32_dir / "rtl/include"), "-o", out / "alu.vvp",
                    overlay / "alu.v", out / "alu_reference.v", HERE / "alu_tb.sv"],
                   out / "alu-compile.log")
        retime.run(["vvp", out / "alu.vvp"], out / "alu.log")
        print((out / "alu.log").read_text(), flush=True)
        retime.verify(args, overlay)
        retime.run([sys.executable, HERE.parent / "mul-pipeline/benchmark.py", "--out", out / "ipc",
                    "--baseline", args.ipc_baseline, "--candidate", out], out / "ipc.log")
        print((out / "ipc.log").read_text(), flush=True)
    elif args.mode == "synth":
        retime.run([ROOT / ".venv-ddr-compat/bin/python", ROOT / "tools/kc705_open_build.py",
                    "synth", "--synapse32-dir", args.synapse32_dir,
                    "--cpu-overlay-dir", overlay, "--build-dir", out / "board"], out / "synth-console.log")
    elif args.mode == "route":
        board = out / "board"
        tool, chipdb = args.nextpnr, args.chipdb
        command = [tool, "--chipdb", chipdb, "--xdc", board / "kc705.xdc", "--freq", "100",
                   "--seed", str(args.seed), "--json", board / "soc.json", "--write", board / "routed.json",
                   "--report", board / "report.json", "--log", board / "route.log"]
        paths += [tool, chipdb, board / "kc705.xdc", board / "soc.json", board / "synth.ys", board / "firmware.hex"]
        manifest = {"command": list(map(str, command)), "seed": args.seed,
                    "allow_const_holdouts": args.allow_const_holdouts,
                    "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
        (board / "route-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        with (board / "route-console.log").open("w") as log:
            import os
            env = dict(os.environ, NEXTPNR_ALLOW_CONST_HOLDOUTS="1") if args.allow_const_holdouts else None
            rc = subprocess.run(list(map(str, command)), stdout=log,
                                stderr=subprocess.STDOUT, env=env).returncode
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
