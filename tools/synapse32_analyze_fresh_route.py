#!/usr/bin/env python3
"""Expand a fresh KC705 route timing graph; report diagnostics, never signoff."""
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from synapse32_apply_bram_timing import apply_model as bram_model
from synapse32_cpu_preg_dsp_model import apply_model as dsp_model
from synapse32_lutram_timing_model import apply_model as lutram_model
from synapse32_missing_cell_arcs import audit as arc_audit
from synapse32_kc705_grade2_limits import bram_limits, dsp_limits, lutram_limits, verify_board
from synapse32_analyze_timing_endpoints import analyze


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--route", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    route, out = a.route.resolve(), a.out.resolve()
    assert not out.exists()
    report = json.loads((route / "report.json").read_text())
    cells = json.loads((route / "routed.json").read_text())["modules"]["top"]["cells"]
    board = verify_board()
    ds182 = Path("build-dsp-preg-timing/ds182.txt").resolve()
    limits = {"bram": bram_limits(ds182.read_text()),
              "dsp": dsp_limits(ds182.read_text()),
              "lutram": lutram_limits(ds182.read_text())}
    rows = [line.rstrip("\n").split("\t") for line in (route / "timing-graph.tsv").open()]
    assert rows[0] == ["VERSION", "1"]
    rows, _ = bram_model(rows, cells, limits["bram"])
    rows, _ = lutram_model(rows, cells, limits["lutram"])
    missing = arc_audit(rows, cells)
    rows += [["CELLARC", arc["cell"], arc["input"], arc["output"], "0.1"]
             for arc in missing["missing_carry_arcs"]]
    rows, coverage = dsp_model(rows, cells, limits["dsp"], pcout_ns=0)
    assert not coverage["unknown_delays"]
    counts = Counter()
    for row in rows:
        if row[0] != "CLOCK" or row[1] not in cells or cells[row[1]]["type"] != "SLICE_FFX":
            continue
        if row[2] == "Q":
            assert abs(float(row[8]) - 0.1) < 1e-6
            bel = cells[row[1]]["attributes"]["NEXTPNR_BEL"].rsplit("/", 1)[1]
            assert re.fullmatch(r"[ABCD](?:5)?FF", bel)
            row[8] = "0.32" if "5FF" in bel else "0.27"
            counts["5ff_q" if "5FF" in bel else "ff_q"] += 1
        elif row[2] in ("CE", "SR"):
            assert abs(float(row[6]) - 0.1) < 1e-6
            row[6] = "0.20" if row[2] == "CE" else "0.31"
            counts["setup_" + row[2]] += 1
    out.mkdir(parents=True)
    graph = out / "mapped-graph.tsv"
    graph.write_text("".join("\t".join(row) + "\n" for row in rows))
    result = analyze(graph)
    assert not result["unresolved_nodes"]
    (out / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    record = {
        "scope": "Expanded mapped FF/control diagnostic on a fresh KC705 route; generic carry, DSP cascade, clocks, hold, and DDR IO are not fully qualified.",
        "physical_100mhz_accepted": False,
        "route": str(route), "native_fmax": report["fmax"],
        "counts": dict(counts), "maxima": result["maxima"],
        "over_10ns_clk_endpoints": sum(e["arrival_ns"] > 10 for e in result["endpoints"]
                                       if e.get("source_clock") == e.get("sink_clock") == "clk"),
        "sha256": {str(q): sha(q) for q in (route / "routed.json", route / "report.json",
                                            route / "timing-graph.tsv", ds182, board,
                                            Path(__file__).resolve(), graph)},
    }
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k != "sha256"}, indent=2))


if __name__ == "__main__":
    main()
