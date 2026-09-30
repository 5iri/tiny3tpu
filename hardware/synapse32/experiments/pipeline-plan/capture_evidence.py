#!/usr/bin/env python3
"""Read-only source/route inspection; writes evidence only beside this script."""
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = Path(os.environ.get("SYNAPSE32_SOURCE", ROOT.parent / "synapse32"))
route = ROOT / "build-ddr-divider/route.log"
netlist = ROOT / "build-ddr-divider/soc.json"
lines = route.read_text().splitlines()
start = next(i for i, s in enumerate(lines) if "Critical path report for clock 'soc.cpu_clk'" in s)
end = next(i for i in range(start, len(lines)) if "ns logic," in lines[i])
net = json.loads(netlist.read_text())["modules"]["kc705_synapse32_top"]
aliases = defaultdict(list)
for name, data in net["netnames"].items():
    if name.startswith("soc.cpu."):
        for index, bit in enumerate(data["bits"]):
            aliases[bit].append(f"{name}[{index}]")
cells = {}
for suffix in ("198147", "198145", "198226"):
    name, data = next((n, c) for n, c in net["cells"].items()
                      if n.endswith("parse_blif$" + suffix))
    cells[name] = {"type": data["type"], "ports": {
        port: {"bits": bits, "cpu_aliases": sorted({a for b in bits for a in aliases[b]})}
        for port, bits in data["connections"].items()}}
files = [route, netlist, ROOT / "build-ddr-divider/synth.ys",
         ROOT / "build-ddr-forwarding/route.log",
         HERE.parent / "forwarding/BOARD_RESULTS.md"]
files += [HERE.parent / "divider" / n for n in ("riscv_cpu.v", "execution_unit.v", "alu.v", "divider.v")]
files += [SOURCE / "rtl/pipeline_stages" / n for n in
          ("ID_EX.v", "IF_ID.v", "EX_MEM.v", "MEM_WB.v", "forwarding_unit.v", "load_use_detector.v")]
files += [SOURCE / "rtl" / n for n in
          ("writeback.v", "core_modules/registerfile.v", "core_modules/csr_file.v", "include/instr_defines.vh")]
files += [HERE / n for n in ("forward_lookahead.sv", "forward_lookahead_tb.sv", "verify.sh", "README.md")]
report = {
    "scope": "source and existing route inspection; no synthesis or route launched",
    "route_path_lines": [start + 1, end + 1],
    "route_cpu_path": lines[start:end + 1],
    "route_final_frequencies": [s for s in lines if "Max frequency" in s][-4:],
    "mapped_forwarding_path_cells": cells,
    "prototype_result": (HERE / "build/test.log").read_text().splitlines()[0],
    "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
}
(HERE / "evidence.json").write_text(json.dumps(report, indent=2) + "\n")
print(report["prototype_result"])
print(f"Captured {len(files)} input hashes and existing route lines {start+1}-{end+1}")
