#!/usr/bin/env python3
"""Reproduce locality probes without changing the input design."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def summarize(log):
    text = Path(log).read_text(errors="replace")
    rows = re.findall(r"Max frequency for clock\s+'([^']+)': ([\d.]+) MHz \((PASS|FAIL) at ([\d.]+) MHz\)", text)
    return {
        "clock_observations": [dict(clock=c, achieved_mhz=float(a), status=s, target_mhz=float(t))
                               for c, a, s, t in rows],
        "unsupported_constraints": sorted(set(re.findall(r"[^\n]*(?:not supported|ignored)[^\n]*", text))),
        "errors": re.findall(r"^ERROR:.*", text, re.M),
        "route_complete": bool("Router2 time" in text and "Critical path report" in text
                               and re.search(r"\d+ warnings?, 0 errors", text)),
        "critical_path_headers": re.findall(r"^Info: Critical path.*", text, re.M),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--netlist", type=Path, required=True)
    parser.add_argument("--xdc", type=Path, required=True)
    parser.add_argument("--nextpnr", type=Path, default=Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx"))
    parser.add_argument("--chipdb", type=Path, default=Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin"))
    parser.add_argument("--variant", choices=["density060", "density080"], required=True)
    parser.add_argument("--parent-log", type=Path)
    parser.add_argument("--route", action="store_true", help="Full route with a private two-worker router2 build")
    args = parser.parse_args()
    if args.route:
        private_source = args.nextpnr.resolve().parent / "router2.cc"
        if not private_source.is_file() or "if (threads.size() == 2)" not in private_source.read_text():
            parser.error("--route requires the private two-worker build described in README.md")
    # The supplied router2 launches four workers; full routing needs the private cap.
    # HeAP uses one x-axis worker while the main thread solves y: two workers.
    out = Path(tempfile.mkdtemp(prefix="synapse32-placement-" + args.variant + "-", dir="/tmp"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEXTPNR_")}
    overrides = {"NEXTPNR_PLACER_BETA": "0.6" if args.variant == "density060" else "0.8",
                 "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "VECLIB_MAXIMUM_THREADS": "2"}
    env.update(overrides)
    inputs = {k: str(getattr(args, k).resolve()) for k in ("netlist", "xdc", "nextpnr", "chipdb")}
    hashes = {k: digest(v) for k, v in inputs.items()}
    cmd = [inputs["nextpnr"], "--chipdb", inputs["chipdb"], "--json", inputs["netlist"],
           "--xdc", inputs["xdc"], "--freq", "100", "--seed", "4", "--placer", "heap",
           "--write", str(out / ("routed.json" if args.route else "placed.json")), "--report", str(out / "report.json"),
           "--log", str(out / "nextpnr.log")]
    if not args.route:
        cmd.append("--no-route")
    manifest = dict(command=cmd, environment=overrides, inputs=inputs, sha256=hashes,
                    scope="global HeAP density; CPU locality measurement; no hard CPU region",
                    stage="routed diagnostic" if args.route else "placement only; timing is estimated, not routed",
                    physical_ready=False, parent_log=str(args.parent_log) if args.parent_log else None)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(out, flush=True)
    with (out / "console.log").open("w") as log:
        result = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    manifest["returncode"] = result.returncode
    manifest["input_hashes_unchanged"] = hashes == {k: digest(v) for k, v in inputs.items()}
    manifest["result"] = summarize(out / "nextpnr.log")
    if (out / "report.json").is_file():
        manifest["result"]["end_of_run_fmax"] = json.loads((out / "report.json").read_text())["fmax"]
    manifest["result"]["route_complete"] = bool(args.route and result.returncode == 0
        and manifest["result"]["critical_path_headers"])
    if args.parent_log:
        manifest["parent_log_snapshot"] = summarize(args.parent_log)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["result"], indent=2))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
