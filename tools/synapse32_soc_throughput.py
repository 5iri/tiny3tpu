#!/usr/bin/env python3
"""Report useful work per system cycle and an exclusive observed runtime partition."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--baseline", type=Path, required=True)
parser.add_argument("--candidate", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
results = {}
inputs = [args.baseline, args.candidate]
for label, path in zip(("legacy", "packed"), inputs[:]):
    observed = json.loads(path.read_text())
    assert observed["unchanged_firmware_and_profiles"]
    reference = Path(observed["reference"]) / "system/results.json"
    inputs.append(reference)
    original = json.loads(reference.read_text())
    jobs = observed["jobs"]
    total = original["metrics"]["system_cycles"]
    gemm = sum(j["system_cycles"] for j in jobs)
    macs = sum(j["required_useful_macs"] for j in jobs)
    phases = {k: sum(j[k] for j in jobs) for k in
              ("dma_only_cycles", "tpu_only_cycles", "both_busy_cycles", "neither_busy_cycles")}
    assert sum(phases.values()) == gemm and total >= gemm
    phases["outside_gemm_cycles"] = total - gemm
    assert sum(phases.values()) == total
    results[label] = {
        "shapes": [j["shape_mkn"] for j in jobs], "useful_macs": macs,
        "useful_arithmetic_ops": 2 * macs, "total_system_cycles": total,
        "gemm_system_cycles": gemm, "full_test_macs_per_cycle": macs / total,
        "gemm_macs_per_cycle": macs / gemm,
        "full_test_useful_pe_capacity": macs / (32 * total),
        "gemm_useful_pe_capacity": macs / (32 * gemm),
        "core_active_useful_pe_capacity": macs / (16 * sum(j["core_busy_cycles_sum"] for j in jobs)),
        "controller_active_useful_pe_capacity": macs / (32 * sum(j["top_busy_cycles"] for j in jobs)),
        "cpu_enabled_fraction_within_gemm": sum(j["cpu_enabled_edges"] for j in jobs) / gemm,
        "exclusive_partition_cycles": phases,
        "cpu_memory_pending_cycles_within_gemm_overlapping": sum(j["cpu_external_pending_cycles"] for j in jobs),
    }
assert results["legacy"]["shapes"] == results["packed"]["shapes"]
assert results["legacy"]["useful_macs"] == results["packed"]["useful_macs"]
results["definitions"] = {
    "work": "sum(M*K*N) useful MACs, or twice that many arithmetic operations; padding excluded",
    "full_test": "Complete diagnostic program, including boot, self-test, input generation, GEMM and caller verification",
    "gemm": "Sum of GEMM entry-to-return windows, including firmware orchestration and memory waits",
    "partition": "Exclusive DMA/TPU busy-state observations inside GEMM plus all cycles outside GEMM",
    "limitations": "Behavioral memory, not physical DDR contention. Busy states do not establish stall causes. Outside-GEMM phases and neither-busy CPU work are not separately attributed yet. No inference workload is tested.",
}
results["sha256"] = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs + [Path(__file__)]}
args.out.mkdir(parents=True, exist_ok=True)
(args.out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
lines = ["# Whole-system throughput", "", "45-shape diagnostic workload; useful work excludes padded MACs.", "",
         "| Metric | Baseline | Candidate |", "|---|---:|---:|"]
for title, key, fmt in [("Useful MACs", "useful_macs", ",d"),
                        ("Total diagnostic system cycles", "total_system_cycles", ",d"),
                        ("Useful MACs / total system cycle", "full_test_macs_per_cycle", ".8f"),
                        ("Useful MACs / GEMM system cycle", "gemm_macs_per_cycle", ".8f"),
                        ("Useful PE capacity, whole diagnostic", "full_test_useful_pe_capacity", ".6%"),
                        ("Useful PE capacity, GEMM windows", "gemm_useful_pe_capacity", ".6%"),
                        ("Useful PE capacity, core-active windows", "core_active_useful_pe_capacity", ".4%"),
                        ("Useful PE capacity, controller-active windows", "controller_active_useful_pe_capacity", ".4%")]:
    lines.append(f"| {title} | {results['legacy'][key]:{fmt}} | {results['packed'][key]:{fmt}} |")
lines += ["", "## Exclusive runtime partition", "",
          "| Observed category | Baseline cycles | Candidate cycles |", "|---|---:|---:|"]
for key, label in [("outside_gemm_cycles", "Outside GEMM: boot/setup/caller verification"),
                   ("dma_only_cycles", "DMA busy, TPU idle"), ("tpu_only_cycles", "TPU busy, DMA idle"),
                   ("both_busy_cycles", "DMA and TPU busy together"),
                   ("neither_busy_cycles", "Both idle inside GEMM")]:
    lines.append(f"| {label} | {results['legacy']['exclusive_partition_cycles'][key]:,} | {results['packed']['exclusive_partition_cycles'][key]:,} |")
lines += ["", "These categories sum exactly to total runtime. CPU memory-pending cycles overlap",
          "them and must not be added as another exclusive category. Neither-busy time",
          "includes software work and CPU memory latency; it is not proven DDR starvation.", "",
          "MAC means one multiply-accumulate; count two arithmetic operations per MAC if",
          "reporting operations/cycle. Multiply by the actual system clock to obtain MAC/s.",
          "The 100 MHz system timing target is not closed, so no 100 MHz hardware rate is claimed.", "",
          "Core-active capacity uses 16 PE slots times the sum of the two core-busy",
          "counters (CLEAR/FEED/FLUSH/CAPTURE), correctly weighting independently active",
          "cores. Controller-active capacity also includes local operand loading. Useful",
          "MAC counts are algorithmic; these counters do not directly observe PE-valid work.", "",
          "The current staged CPU integration requires at least four system clocks per",
          "enabled CPU edge. Disabled CPU edges are therefore not equivalent to avoidable",
          "memory stalls. The enabled-edge fraction alone cannot attribute runtime.", "",
          "The full-test denominator includes diagnostic self-test and verification, not just",
          "production work. Report a separately delimited request-to-result window for deployed",
          "inference, with cold-start and steady-state results separate. No inference test exists",
          "in this measurement. DMA/TPU activity is observed, not a causal stall attribution."]
(args.out / "report.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
