#!/usr/bin/env python3
"""Extract CPU connectivity and actual critical-path locality, without mutations."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def inspect_netlist(path):
    design = json.loads(Path(path).read_text())
    mod = design["modules"]["kc705_synapse32_top"]
    cells, nets = mod["cells"], mod["netnames"]
    clock = set(nets["soc.cpu_clk"]["bits"])
    cpu_ffs = {name for name, cell in cells.items()
               if cell["type"].startswith("FD") and clock.intersection(cell["connections"].get("C", []))}
    drivers = {}
    for name, cell in cells.items():
        for port, bits in cell["connections"].items():
            if cell.get("port_directions", {}).get(port) == "output":
                for bit in bits:
                    if isinstance(bit, int):
                        drivers[bit] = name
    # Combinational predecessors of CPU-register data and enable pins. Stop at
    # sequential and hard macro boundaries, and omit reset/clock control cones.
    combinational = {"LUT1", "LUT2", "LUT3", "LUT4", "LUT5", "LUT6", "LUT6_2",
                     "MUXF7", "MUXF8", "CARRY4", "INV"}
    selected = set(cpu_ffs)
    todo = [b for n in cpu_ffs for p in ("D", "CE") for b in cells[n]["connections"].get(p, [])]
    while todo:
        bit = todo.pop()
        name = drivers.get(bit)
        if name is None or name in selected or cells[name]["type"] not in combinational:
            continue
        selected.add(name)
        cell = cells[name]
        todo.extend(b for p, bits in cell["connections"].items()
                    if cell["port_directions"].get(p) == "input" for b in bits)
    return dict(top="kc705_synapse32_top", total_cells=len(cells), cpu_clock_bits=sorted(clock),
                cpu_clocked_ff_count=len(cpu_ffs), cpu_data_enable_cone_count=len(selected),
                cone_types=dict(Counter(cells[n]["type"] for n in selected)),
                cpu_net_alias_count=sum(n.startswith("soc.cpu.") for n in nets),
                selected_cells=sorted(selected),
                caveat="Connectivity cone can include shared logic; hard macros and reset/clock cones excluded.")


def inspect_paths(path):
    text = Path(path).read_text(errors="replace")
    sections = re.split(r"Info: Critical path report for ", text)[1:]
    result = []
    for section in sections:
        end = re.search(r"Info: ([\d.]+) ns logic, ([\d.]+) ns routing", section)
        if not end:
            continue
        body = section[:end.end()]
        arcs = []
        for m in re.finditer(r"Info:\s+([\d.]+)\s+([\d.]+)\s+Net (.*?) budget .*?\((\d+),(\d+)\) -> \((\d+),(\d+)\)", body):
            delay, total, net, x0, y0, x1, y1 = m.groups()
            x0, y0, x1, y1 = map(int, (x0, y0, x1, y1))
            arcs.append(dict(net=net, delay_ns=float(delay), start=[x0, y0], end=[x1, y1],
                             manhattan_tiles=abs(x1-x0)+abs(y1-y0)))
        points = [p for a in arcs for p in (a["start"], a["end"])]
        sources = re.findall(r"Source (.*)", body)
        sinks = re.findall(r"Setup (.*)", body)
        result.append(dict(header=body.splitlines()[0], logic_ns=float(end[1]), routing_ns=float(end[2]),
                           source=sources[0] if sources else None, sink=sinks[-1] if sinks else None,
                           source_stage_count=len(sources), arc_count=len(arcs),
                           bbox=[min(p[0] for p in points), min(p[1] for p in points),
                                 max(p[0] for p in points), max(p[1] for p in points)] if points else None,
                           total_manhattan_tiles=sum(a["manhattan_tiles"] for a in arcs),
                           longest_arcs=sorted(arcs, key=lambda a: a["delay_ns"], reverse=True)[:10],
                           named_cpu_nets=[a["net"] for a in arcs if a["net"].startswith("soc.cpu.")]))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--netlist", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    result = {}
    if args.netlist:
        result["netlist"] = inspect_netlist(args.netlist)
    if args.log:
        result["paths"] = inspect_paths(args.log)
    print(json.dumps(result, indent=2))
