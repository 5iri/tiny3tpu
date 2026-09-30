#!/usr/bin/env python3
"""Record a matched KC705 PE/PREG route comparison without claiming signoff."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(path):
    cells = json.loads(path.read_text())["modules"]["kc705_synapse32_top"]["cells"]
    counts = Counter(cell["type"] for cell in cells.values())
    dsps = [cell for cell in cells.values() if cell["type"] == "DSP48E1"]
    return {
        "cells": len(cells),
        "fabric_ffs": sum(counts[t] for t in ("FDRE", "FDCE", "FDSE", "FDPE")),
        "dsps": len(dsps),
        "preg_dsps": sum(int(cell["parameters"]["PREG"], 2) == 1 for cell in dsps),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline_soc", "candidate_soc", "baseline_report", "candidate_report", "out"):
        parser.add_argument("--" + name.replace("_", "-"), required=True, type=Path)
    args = parser.parse_args()
    paths = [args.baseline_soc, args.candidate_soc, args.baseline_report, args.candidate_report]
    baseline, candidate = inventory(args.baseline_soc), inventory(args.candidate_soc)
    b_fmax = json.loads(args.baseline_report.read_text())["fmax"]
    c_fmax = json.loads(args.candidate_report.read_text())["fmax"]
    comparable = (
        baseline["dsps"] == candidate["dsps"] == 36
        and baseline["preg_dsps"] == 0
        and candidate["preg_dsps"] == 32
        and baseline["fabric_ffs"] - candidate["fabric_ffs"] == 1023
    )
    output = {
        "passed": comparable,
        "scope": "Matched-seed exploratory route; registered DSP and other known paths are not fully timed.",
        "baseline": baseline,
        "candidate": candidate,
        "fmax_mhz": {clock: {"baseline": b_fmax[clock]["achieved"], "candidate": c_fmax[clock]["achieved"]}
                     for clock in sorted(set(b_fmax) & set(c_fmax))},
        "physical_100mhz_accepted": False,
        "sha256": {str(path.resolve()): sha(path) for path in paths},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n")
    if not comparable:
        raise SystemExit("PE mapping comparison failed")
    print(json.dumps(output["fmax_mhz"], indent=2))


if __name__ == "__main__":
    main()
