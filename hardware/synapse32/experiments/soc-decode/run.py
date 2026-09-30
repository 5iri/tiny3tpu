#!/usr/bin/env python3
"""SoC address-decode slimming for the sys/cross timing paths.

The measured cpu->clk cross path (12.3ns vs 10ns budget) runs EX/MEM
instruction -> memory-unit addresses -> dram_soc peripheral decode/procmux.
The deepest single decode term is the boot range check: a 32-bit subtract
plus compare. For the production BOOT_WORDS=16384 geometry (64 KiB), the
condition is exactly the 16-bit prefix req_addr[31:16]==16'h8000, which
removes the carry chain from the decode cone. All other decodes, the boot
index path, state elements, handshake and cycle behavior are unchanged, so
the change is provably equivalent combinational logic (see prove_tb.sv).
Production board RTL and upstream Synapse32 are not modified.
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

SOC = ROOT / "hardware/synapse32/synapse32_dram_soc.sv"
OLD = """    wire boot_address = req_addr>=32'h80000000 &&
        (req_addr-32'h80000000)<BOOT_WORDS*4;"""
NEW = """    // BOOT_WORDS=16384 is 64 KiB: prefix compare, no subtract carry chain.
    // Other BOOT_WORDS keep the original range expression.
    wire boot_address = (BOOT_WORDS == 16384)
        ? (req_addr[31:16] == 16'h8000)
        : (req_addr>=32'h80000000 && (req_addr-32'h80000000)<BOOT_WORDS*4);"""


def prepare(out):
    overlay = out / "system-overlay"
    overlay.mkdir(parents=True, exist_ok=True)
    original = SOC.read_text()
    if OLD not in original:
        raise SystemExit("production SoC decode anchor changed; re-derive the overlay")
    (overlay / "synapse32_dram_soc.sv").write_text(original.replace(OLD, NEW))
    return overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "prove", "verify", "synth", "route"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--synapse32-dir", type=Path, default=ROOT.parent / "synapse32")
    parser.add_argument("--cpu-overlay-dir", type=Path, default=None,
                        help="CPU overlay for sim/synth/route (e.g. split-mul overlay)")
    parser.add_argument("--nextpnr", type=Path,
                        default=Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx"))
    parser.add_argument("--chipdb", type=Path,
                        default=Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin"))
    parser.add_argument("--seed", type=int, default=4)
    parser.add_argument("--allow-const-holdouts", action="store_true",
                        help="Pass NEXTPNR_ALLOW_CONST_HOLDOUTS=1 for timing "
                             "diagnostics only; output stays rejected for bitstream use")
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.synapse32_dir = args.synapse32_dir.resolve()
    out = args.out
    overlay = prepare(out)
    paths = sorted(overlay.glob("*.sv")) + [Path(__file__), HERE / "prove_tb.sv"]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out / (args.mode + "-sources.json")).write_text(json.dumps(hashes, indent=2) + "\n")
    if args.mode == "prove":
        retime.run(["iverilog", "-g2012", "-s", "soc_decode_prove_tb",
                    "-o", out / "prove.vvp", HERE / "prove_tb.sv"], out / "prove-compile.log")
        retime.run(["vvp", out / "prove.vvp"], out / "prove.log")
        print((out / "prove.log").read_text(), flush=True)
    elif args.mode == "verify":
        # The overlay changes one combinational decode term, proved equivalent
        # for all addresses; state elements and cycle behavior are unchanged.
        # The CPU/DRAM suites run the production SoC plus the CPU overlay to
        # confirm the harness still passes around the proved delta.
        if args.cpu_overlay_dir is None:
            raise SystemExit("verify needs --cpu-overlay-dir for the CPU/sim overlay")
        cpu_overlay = Path(args.cpu_overlay_dir).resolve()
        import types
        sim_args = types.SimpleNamespace(synapse32_dir=args.synapse32_dir, out=out)
        retime.verify(sim_args, cpu_overlay)
    elif args.mode == "synth":
        if args.cpu_overlay_dir is None:
            raise SystemExit("synth needs --cpu-overlay-dir for the CPU overlay")
        retime.run([ROOT / ".venv-ddr-compat/bin/python", ROOT / "tools/kc705_open_build.py",
                    "synth", "--synapse32-dir", args.synapse32_dir,
                    "--cpu-overlay-dir", Path(args.cpu_overlay_dir).resolve(),
                    "--system-overlay-dir", overlay,
                    "--build-dir", out / "board"], out / "synth-console.log")
    elif args.mode == "route":
        board = out / "board"
        tool, chipdb = args.nextpnr, args.chipdb
        command = [tool, "--chipdb", chipdb, "--xdc", board / "kc705.xdc", "--freq", "100",
                   "--seed", str(args.seed), "--json", board / "soc.json", "--write", board / "routed.json",
                   "--report", board / "report.json", "--log", board / "route.log"]
        paths += [tool, chipdb, board / "kc705.xdc", board / "soc.json", board / "synth.ys", board / "firmware.hex"]
        manifest = {"command": list(map(str, command)), "seed": args.seed,
                    "allow_const_holdouts": args.allow_const_holdouts,
                    "system_overlay_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                              for p in sorted(overlay.glob("*.sv"))},
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
