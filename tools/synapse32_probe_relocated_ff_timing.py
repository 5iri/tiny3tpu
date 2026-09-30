#!/usr/bin/env python3
"""Apply the existing expanded grade-2 and mapped FF models to a new route."""
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


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--route", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
a = parser.parse_args()
route, out = a.route.resolve(), a.out.resolve()
assert not out.exists()
manifest = json.loads((route / "manifest.json").read_text())
assert manifest["passed"]
board = verify_board()
ds182 = Path("build-dsp-preg-timing/ds182.txt").resolve()
limits = {"bram": bram_limits(ds182.read_text()),
          "dsp": dsp_limits(ds182.read_text()),
          "lutram": lutram_limits(ds182.read_text())}
cells = json.loads((route / "routed.json").read_text())["modules"]["top"]["cells"]
source = route / "timing-graph.tsv"
rows = [line.rstrip("\n").split("\t") for line in source.open()]
assert rows[0] == ["VERSION", "1"]
rows, _ = bram_model(rows, cells, limits["bram"])
rows, _ = lutram_model(rows, cells, limits["lutram"])
missing = arc_audit(rows, cells)
assert missing["missing_carry_arcs"]
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
assert counts == {"ff_q": 11225, "5ff_q": 3143, "setup_CE": 8413, "setup_SR": 10976}
out.mkdir(parents=True)
graph = out / "mapped-graph.tsv"
graph.write_text("".join("\t".join(row) + "\n" for row in rows))
analysis = analyze(graph)
assert not analysis["unresolved_nodes"]
(out / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")
record = {"passed": True, "scope": "Expanded grade-2 and mapped FF/control sensitivity only; DSP cascade and carry delays remain symbolic, and clock skew, hold and DDR IO are not signed off.",
          "physical_100mhz_accepted": False, "counts": dict(counts), "maxima": analysis["maxima"],
          "sha256": {str(path): sha(path) for path in
                     (route / "manifest.json", route / "routed.json", source, ds182,
                      Path(__file__).resolve(), graph, board)}}
(out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
print("worst mapped expanded path", max(x["arrival_ns"] for x in analysis["maxima"]), "ns")
