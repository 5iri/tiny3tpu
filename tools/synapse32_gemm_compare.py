#!/usr/bin/env python3
"""Compare paired GEMM-scoped CPU and accelerator measurements across shapes."""
import argparse
import hashlib
import json
from pathlib import Path


def aggregate(jobs):
    instructions = sum(j["cpu_instructions"] for j in jobs)
    edges = sum(j["cpu_enabled_edges"] for j in jobs)
    cycles = sum(j["system_cycles"] for j in jobs)
    return {
        "calls": len(jobs), "instructions": instructions, "enabled_cpu_cycles": edges,
        "system_cycles": cycles, "pooled_ipc": instructions / edges,
        "equal_shape_mean_ipc": sum(j["cpu_instructions"] / j["cpu_enabled_edges"] for j in jobs) / len(jobs),
        "useful_pe_capacity_fraction": sum(j["required_useful_macs"] for j in jobs) / (32 * cycles),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sources = [args.baseline.resolve(), args.candidate.resolve()]
    a, b = [json.loads(p.read_text()) for p in sources]
    assert a["unchanged_firmware_and_profiles"] and b["unchanged_firmware_and_profiles"]
    assert a["measurement"] == b["measurement"] and a["denominator"] == b["denominator"]
    assert a["jobs"] and len(a["jobs"]) == len(b["jobs"])
    rows = []
    for x, y in zip(a["jobs"], b["jobs"]):
        for key in ("shape_mkn", "launches", "required_useful_macs", "scheduled_tile_macs"):
            assert x[key] == y[key], "Unpaired workload: " + key
        old_ipc = x["cpu_instructions"] / x["cpu_enabled_edges"]
        new_ipc = y["cpu_instructions"] / y["cpu_enabled_edges"]
        rows.append({
            "shape_mkn": x["shape_mkn"], "baseline_ipc": old_ipc, "candidate_ipc": new_ipc,
            "baseline_instructions": x["cpu_instructions"], "candidate_instructions": y["cpu_instructions"],
            "baseline_cpu_cycles": x["cpu_enabled_edges"], "candidate_cpu_cycles": y["cpu_enabled_edges"],
            "baseline_system_cycles": x["system_cycles"], "candidate_system_cycles": y["system_cycles"],
            "cycle_reduction_fraction": 1 - y["system_cycles"] / x["system_cycles"],
            "ipc_improved": new_ipc > old_ipc,
        })
    old, new = aggregate(a["jobs"]), aggregate(b["jobs"])
    result = {
        "baseline": old, "candidate": new, "shapes": rows,
        "ipc_improved_shapes": sum(r["ipc_improved"] for r in rows),
        "faster_shapes": sum(r["cycle_reduction_fraction"] > 0 for r in rows),
        "total_cycle_reduction_fraction": 1 - new["system_cycles"] / old["system_cycles"],
        "pooled_ipc_formula": "sum(instructions) / sum(enabled CPU cycles), one call per listed shape",
        "equal_shape_mean_formula": "sum(shape IPC) / number of shapes; descriptive, not pooled execution IPC",
        "scope": a["measurement"], "limitations": a["limitations"],
        "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources + [Path(__file__).resolve()]},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# GEMM shape sweep: baseline versus candidate", "",
             f"{len(rows)} distinct M×K×N shapes, one call each. Only GEMM calls are counted; boot,",
             "input generation and caller result verification are excluded. All results were",
             "checked by firmware and the independent host scoreboard before measurement.", "",
             "| GEMM-scoped metric | Baseline | Candidate |", "|---|---:|---:|"]
    for label, key, fmt in [
        ("Completed instructions", "instructions", ",d"),
        ("Enabled CPU cycles", "enabled_cpu_cycles", ",d"),
        ("Pooled IPC", "pooled_ipc", ".6f"),
        ("Equal-shape mean IPC", "equal_shape_mean_ipc", ".6f"),
        ("System cycles", "system_cycles", ",d"),
        ("Useful PE capacity", "useful_pe_capacity_fraction", ".6%"),
    ]:
        lines.append(f"| {label} | {old[key]:{fmt}} | {new[key]:{fmt}} |")
    lines += ["", f"The candidate reduces total GEMM cycles by {result['total_cycle_reduction_fraction']:.2%}.",
              f"IPC improves on {result['ipc_improved_shapes']} of {len(rows)} shapes; {result['faster_shapes']} of {len(rows)} calls finish sooner.", "",
              "Pooled IPC is `sum(instructions) / sum(enabled CPU cycles)`. It is the actual",
              "ratio for this suite and equals a CPU-cycle-weighted mean of the shape IPCs.",
              "An arithmetic mean gives each shape equal influence but is a different statistic.",
              "For a deployment with repeat counts `w`, use `sum(w*instructions)/sum(w*cycles)`.", "",
              "This is a representative synthetic sweep, not every possible GEMM or a measured",
              "production workload distribution. It covers small matrices, dimensions around",
              "4×4/8-wide tile boundaries, square matrices, long K, vector-like cases, tall/wide",
              "matrices and padded tails. Memory is behavioral, with no physical DDR contention.", "",
              "| M×K×N | Baseline IPC | Candidate IPC | Baseline system cycles | Candidate system cycles | Cycle reduction |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        shape = "×".join(map(str, row["shape_mkn"]))
        lines.append(f"| {shape} | {row['baseline_ipc']:.6f} | {row['candidate_ipc']:.6f} | "
                     f"{row['baseline_system_cycles']:,} | {row['candidate_system_cycles']:,} | {row['cycle_reduction_fraction']:.2%} |")
    lines += ["", "Source measurements:", ""] + [f"- [{p.parent.name}]({p})" for p in sources]
    (args.out / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("shapes", "sha256")}, indent=2))


if __name__ == "__main__":
    main()
