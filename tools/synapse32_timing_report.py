#!/usr/bin/env python3
"""Summarize one nextpnr invocation per log; never certify DDR signoff.

Example: python3 tools/synapse32_timing_report.py route.log --exit-code 0
For comparisons repeat --exit-code and --provenance (JSON files) in log order.
Exit codes must come from the actual process, not a pipe/tee. Without one a run
is unfinished/unverified. Placement Fmax is never a routed result. The default
contract is the Synapse32 KC705 x64/1 GiB, sys100 DDR400 input/IDELAY200 design.
Clocks without register endpoints need derived-clock evidence, not invented Fmax.
Provenance values are caller attestations: use content hashes, not mutable paths.
"""

import argparse
import json
import math
from pathlib import Path
import re


FINAL_CLOCKS = {"clk": 100.0, "soc.cpu_clk": 100.0,
                "clk200": 200.0, "memory.iodelay_clk": 200.0}
DERIVED_CLOCKS = {
    "clk200": 200.0, "clk": 100.0, "soc.cpu_clk": 100.0,
    "memory.iodelay_clk": 200.0, "memory.main_clkout_buf2": 400.0,
    "memory.main_clkout3": 400.0,
}
COMPARISON_KEYS = (
    "nextpnr_sha256", "chipdb_sha256", "xdc_sha256", "baseline_sha256",
    "seed", "threads", "contract",
)
HASH_KEYS = (*COMPARISON_KEYS[:4], "netlist_sha256")
CONTRACT = "synapse32-kc705-x64-1GiB-sys100-ddr400-input200-idelay200"
NUMBER = r"[0-9]+(?:\.[0-9]+)?"
FMAX = re.compile(
    rf"Max frequency for clock\s+'(.+)':\s*({NUMBER}) MHz "
    rf"\((PASS|FAIL) at ({NUMBER}) MHz\)"
)
DERIVED = re.compile(rf"derived ({NUMBER}) MHz for net '(.+)' \(through (.+)\)")
CROSS_DELAY = re.compile(
    rf"Max delay (posedge|negedge)\s+(\S+)\s+->\s+(posedge|negedge)\s+(\S+)\s*:\s*({NUMBER}) ns"
)
CONSTRAINT_ERROR = re.compile(
    r"(?i)(?:not supported|unsupported|ignored|ignoring|unrecognised|unrecognized|"
    r"unknown|failed|no objects|not found|did not settle)"
)


def summarize(log, exit_code=None, provenance=None, name="<log>"):
    """Return diagnostic evidence and strict acceptance; no filesystem writes."""
    lines = log.splitlines()
    reasons = []
    warnings = []
    derived = {}
    blocks = []
    block = {}
    post_route = False
    routing_finished = False
    invocation_count = 0
    cross_clock_delays = []
    for lineno, line in enumerate(lines, 1):
        if "Propagating clock constraints..." in line:
            invocation_count += 1
        match = DERIVED.search(line)
        if match:
            mhz, clock, through = match.groups()
            derived[clock] = {"mhz": float(mhz), "through": through, "line": lineno}
        if "Router2 time " in line:
            routing_finished = True
        if "Running post-routing legalisation..." in line:
            post_route = True
            blocks = []
            block = {}
        match = FMAX.search(line)
        if post_route and "Max frequency for clock" in line and not match:
            reasons.append("malformed final clock report at line {}".format(lineno))
        if post_route and "FAIL at" in line and not match:
            reasons.append("final constraint failure at line {}".format(lineno))
        if post_route and "Max delay " in line:
            entry = {"line": lineno, "text": line.strip()}
            cross_match = CROSS_DELAY.search(line)
            if cross_match:
                source_edge, source_clock, sink_edge, sink_clock, delay = cross_match.groups()
                entry.update(source_clock=source_clock, sink_clock=sink_clock,
                             source_edge=source_edge, sink_edge=sink_edge, delay_ns=float(delay))
                if {source_clock, sink_clock} == {"clk", "soc.cpu_clk"}:
                    # This contract uses related 100 MHz system/BUFGCE clocks,
                    # without multicycle exceptions. Opposite edges have 5 ns.
                    budget = 10.0 if source_edge == sink_edge else 5.0
                    entry.update(budget_ns=budget, margin_ns=budget-float(delay))
                    if float(delay) > budget:
                        reasons.append("final cross-clock timing failed: {} -> {} ({:.2f} ns > {:.2f} ns)".format(
                            source_clock, sink_clock, float(delay), budget))
            elif "soc.cpu_clk" in line:
                reasons.append("malformed final CPU cross-clock delay at line {}".format(lineno))
            cross_clock_delays.append(entry)
        if post_route and match:
            clock, mhz, status, target = match.groups()
            if clock in block:
                reasons.append("duplicate clock in final timing block: " + clock)
            block[clock] = {"mhz": float(mhz), "target_mhz": float(target),
                            "status": status, "line": lineno}
        elif block and line.strip() not in ("", "Info:"):
            blocks.append(block)
            block = {}
        lower = line.lower()
        if "warning:" in lower:
            warnings.append({"line": lineno, "text": line})
        if CONSTRAINT_ERROR.search(line) and any(token in lower for token in (
                "constraint", "set_", "get_", "xdc", "create_clock")):
            reasons.append("constraint diagnostic at line {}: {}".format(lineno, line.strip()))
        if re.search(r"\b[1-9][0-9]* errors\b", line):
            reasons.append("nonzero error summary at line {}".format(lineno))
        if re.search(r"(?i)(?:^|\s)(?:ERROR|FATAL):", line):
            reasons.append("tool error at line {}: {}".format(lineno, line.strip()))
        if re.search(r"--(?:timing-allow-fail|ignore-loops|ignore-rel-clk|force)\b", line):
            reasons.append("unsafe timing override at line {}".format(lineno))
    if block:
        blocks.append(block)
    clocks = blocks[-1] if blocks else {}
    if invocation_count > 1:
        reasons.append("multiple invocations in one log; split logs before analysis")
    completed = exit_code is not None and routing_finished and post_route and bool(clocks)
    if exit_code is None:
        reasons.append("process completion/exit code not supplied")
    elif exit_code != 0:
        reasons.append("process exited with code {}".format(exit_code))
    if not routing_finished or not post_route or not clocks:
        reasons.append("missing final routed timing evidence (Router2 + post-routing legalisation + Fmax)")
    for clock, target in FINAL_CLOCKS.items():
        if clock not in clocks:
            reasons.append("missing final routed clock: " + clock)
        elif not math.isclose(clocks[clock]["target_mhz"], target, abs_tol=0.01):
            reasons.append("wrong final target for " + clock)
    for clock, target in DERIVED_CLOCKS.items():
        if clock not in derived:
            reasons.append("missing derived clock: " + clock)
        elif not math.isclose(derived[clock]["mhz"], target, abs_tol=0.01):
            reasons.append("wrong derived frequency for " + clock)
    if "soc.cpu_clk" in derived and "BUFGCE" not in derived["soc.cpu_clk"]["through"]:
        reasons.append("CPU clock lacks BUFGCE propagation evidence")
    margins = []
    for clock, result in clocks.items():
        mhz, target = result["mhz"], result["target_mhz"]
        if not math.isfinite(mhz) or not math.isfinite(target) or mhz <= 0 or target <= 0:
            reasons.append("invalid frequency for " + clock)
            result["mhz"] = mhz if math.isfinite(mhz) else None
            result["target_mhz"] = target if math.isfinite(target) else None
            continue
        result["normalized_margin"] = mhz / target - 1.0
        result["period_margin_ns"] = 1000.0 / target - 1000.0 / mhz
        margins.append(result["normalized_margin"])
        if result["status"] != "PASS" or mhz < target:
            reasons.append("final timing failed for " + clock)
    return {
        "name": name, "status": "rejected" if reasons else "diagnostic_pass",
        "accepted": not reasons, "completed": completed, "exit_code": exit_code,
        "ddr_signoff": False,
        "limitations": "Diagnostic nextpnr timing only; no DDR IO, calibration, clock-gating setup/hold or hardware signoff.",
        "reasons": reasons, "warnings": warnings, "final_clocks": clocks,
        "clocks_worst_first": sorted(
            (clock for clock in clocks if "normalized_margin" in clocks[clock]),
            key=lambda clock: (clocks[clock]["normalized_margin"], clock)),
        "derived_clocks": derived,
        "cross_clock_delays": cross_clock_delays,
        "diagnostic_score": min(margins) if margins and completed else None,
        "score_definition": "minimum(final Fmax / target - 1); larger is better",
        "provenance": provenance or {},
    }


def provenance_errors(provenance):
    errors = []
    for key in HASH_KEYS:
        if not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get(key, ""))):
            errors.append("missing/invalid " + key)
    if type(provenance.get("seed")) is not int or provenance["seed"] < 0:
        errors.append("missing/invalid seed")
    if type(provenance.get("threads")) is not int or provenance["threads"] not in (1, 2):
        errors.append("threads must be 1 or 2")
    if provenance.get("contract") != CONTRACT:
        errors.append("missing/wrong contract")
    return errors


def rank_reports(reports):
    """Only accepted results with matched provenance enter a ranking.

    Netlist hashes must be recorded but may differ (the experimental variable).
    Failed timing still has a diagnostic score; rejection is never a pass/rank.
    """
    errors = []
    if not reports:
        errors.append("no reports")
    for report in reports:
        errors.extend(report["name"] + ": " + error
                      for error in provenance_errors(report["provenance"]))
        if not report["accepted"]:
            errors.append(report["name"] + ": rejected report")
    if reports:
        for report in reports[1:]:
            for key in COMPARISON_KEYS:
                if report["provenance"].get(key) != reports[0]["provenance"].get(key):
                    errors.append("comparison mismatch: " + key)
    return {"status": "not_comparable" if errors else "diagnostic_only",
            "reasons": errors,
            "ranking": [] if errors else [r["name"] for r in sorted(
                reports, key=lambda r: (-r["diagnostic_score"], r["name"]))]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--exit-code", action="append", type=int, default=[])
    parser.add_argument("--provenance", action="append", type=Path, default=[])
    args = parser.parse_args(argv)
    for label, values in (("--exit-code", args.exit_code), ("--provenance", args.provenance)):
        if values and len(values) != len(args.logs):
            parser.error(label + " must be supplied once per log, in log order")
    reports = []
    try:
        for index, path in enumerate(args.logs):
            provenance = json.loads(args.provenance[index].read_text()) if args.provenance else {}
            if not isinstance(provenance, dict):
                raise ValueError("provenance must be a JSON object")
            reports.append(summarize(path.read_text(errors="replace"),
                                     args.exit_code[index] if args.exit_code else None,
                                     provenance, str(path)))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    comparison = rank_reports(reports) if len(reports) > 1 else None
    print(json.dumps({"reports": reports, "comparison": comparison}, indent=2, allow_nan=False))
    return 0 if all(r["accepted"] for r in reports) and (
        comparison is None or not comparison["reasons"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
