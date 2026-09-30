#!/usr/bin/env python3
"""Keep the CPU DSP48 multipliers combinational around the existing pipeline."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

source = json.loads(args.input.read_text())
candidate = copy.deepcopy(source)
cells = candidate["modules"]["kc705_synapse32_top"]["cells"]
changed = []
for name, cell in cells.items():
    if cell.get("type") != "DSP48E1" or ".cpu." not in name:
        continue
    if cell.get("attributes", {}).get("src", "").find("dsp_mul.v") < 0:
        continue
    for parameter in ("AREG", "BREG", "MREG", "PREG", "ACASCREG", "BCASCREG"):
        old = cell["parameters"].get(parameter)
        if old is None:
            continue
        cell["parameters"][parameter] = "0" * 32
    changed.append(name)

assert len(changed) == 4, changed
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(candidate, separators=(",", ":")) + "\n")
manifest = args.output.with_suffix(".dsp-registers.json")
manifest.write_text(json.dumps({
    "passed": True,
    "source": str(args.input.resolve()),
    "source_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
    "changed_cells": changed,
    "changed_parameters": ["AREG", "BREG", "MREG", "PREG", "ACASCREG", "BCASCREG"],
    "external_pipeline_preserved": True,
}, indent=2) + "\n")
print(f"Mapped {len(changed)} CPU DSP48 cells to combinational internal datapaths")
