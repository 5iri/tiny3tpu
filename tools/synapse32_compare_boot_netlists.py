#!/usr/bin/env python3
"""Compare flattened board hardware while allowing boot RAM content changes."""
import argparse
import hashlib
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--baseline", type=Path, required=True)
parser.add_argument("--candidate", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
paths = [args.baseline.resolve(), args.candidate.resolve()]
normalized = []
for path in paths:
    m = json.loads(path.read_text())["modules"]["kc705_synapse32_top"]
    graph = {"ports": m["ports"], "cells": {}}
    for name, cell in m["cells"].items():
        # Yosys embeds the generated source directory in ten cell names.
        name = name.replace(str(path.parent.parent), "<BUILD>")
        assert name not in graph["cells"]
        params = dict(cell["parameters"])
        if cell["type"] == "RAMB36E1" and "boot_mem" in name:
            params = {k: v for k, v in params.items() if not re.fullmatch(r"INIT(?:P)?_[0-9A-F]{2}", k)}
        graph["cells"][name] = {"type": cell["type"], "parameters": params,
                                "connections": cell["connections"], "port_directions": cell["port_directions"]}
    normalized.append(graph)
result = {
    "equal_hardware_except_boot_contents": normalized[0] == normalized[1],
    "comparison": "Exact flattened top ports, cell types, connections, directions and parameters. Normalize generated source-directory prefixes in cell names; omit source/debug attributes and only boot RAMB36E1 INIT_xx/INITP_xx contents.",
    "limitation": "Structural comparison, not a new placement/routing result or timing signoff.",
    "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths + [Path(__file__).resolve()]},
    "normalized_sha256": [hashlib.sha256(json.dumps(g, sort_keys=True).encode()).hexdigest() for g in normalized],
}
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["equal_hardware_except_boot_contents"] else 1)
