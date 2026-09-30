#!/usr/bin/env python3
"""Relocate one constrained LUT+FF pair without changing its logic."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from synapse32_pinmap_control_audit import functional_cells
from synapse32_locked_reroute_evidence import routes


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--source", type=Path, required=True)
p.add_argument("--lut", required=True)
p.add_argument("--ff", required=True)
p.add_argument("--site", required=True)
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
source, out = a.source.resolve(), a.out.resolve()
assert not out.exists()
design = json.loads(source.read_text())
module = design["modules"]["top"]
cells, nets = module["cells"], module["netnames"]
lut, ff = cells[a.lut], cells[a.ff]
assert lut["type"] == "SLICE_LUTX" and ff["type"] == "SLICE_FFX"
assert lut["attributes"].get("CONSTR_CHILDREN") == a.ff
assert ff["attributes"].get("CONSTR_PARENT") == a.lut
old_lut = lut["attributes"]["NEXTPNR_BEL"]
old_ff = ff["attributes"]["NEXTPNR_BEL"]
old_site = old_lut.split("/")[0]
assert old_ff.split("/")[0] == old_site
assert old_lut.endswith("/B6LUT") and old_ff.endswith("/BFF")
new_lut, new_ff = a.site + "/B6LUT", a.site + "/BFF"
assert a.site.startswith("SLICE_X") and a.site != old_site
occupied = {c["attributes"].get("NEXTPNR_BEL") for c in cells.values()}
assert new_lut not in occupied and new_ff not in occupied
lut["attributes"]["NEXTPNR_BEL"] = new_lut
ff["attributes"]["NEXTPNR_BEL"] = new_ff
changed_bits = {b for bits in lut["connections"].values() for b in bits}
changed_bits |= {b for pin in ("D", "Q") for b in ff["connections"][pin]}
shared_bits = {b for pin in ("CK", "SR") for b in ff["connections"].get(pin, [])}
released, locked = [], []
for name, net in nets.items():
    attrs = net.get("attributes", {})
    route = attrs.get("ROUTING", "")
    if set(net["bits"]) & changed_bits:
        attrs.pop("ROUTING", None)
        released.append(name)
    elif route.strip():
        fields = route.split(";")
        assert len(fields) % 3 == 0
        for i in range(0, len(fields), 3):
            fields[i + 2] = "4"
        attrs["ROUTING"] = ";".join(fields)
        locked.append(name)
assert released and locked
out.mkdir()
inp = out / "input.json"
inp.write_text(json.dumps(design, separators=(",", ":")) + "\n")
tool = Path("/tmp/tiny3tpu-nextpnr-placement-label-replay/nextpnr-xilinx")
chipdb = Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin")
xdc = Path("build-grade2-pre-fixup-routing-control/restored-clocks.xdc").resolve()
cmd = [str(tool), "--chipdb", str(chipdb), "--xdc", str(xdc), "--freq", "100", "--seed", "5",
       "--json", str(inp), "--write", str(out / "routed.json"), "--report", str(out / "report.json"),
       "--log", str(out / "route.log"), "--no-pack", "--placer", "sa", "--starttemp", "0"]
env = {k: v for k, v in os.environ.items() if not k.startswith(("NEXTPNR_", "TINY3TPU_"))}
env.update(TINY3TPU_REPLAY_PLACEMENT_LABELS="1", TINY3TPU_LOSSLESS_ROUTE_NAMES="1",
           TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS="1",
           TINY3TPU_TIMING_GRAPH=str(out / "timing-graph.tsv"))
with (out / "console.log").open("w") as log:
    rc = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
record = {"passed": False, "source": str(source),
          "moves": {a.lut: [old_lut, new_lut], a.ff: [old_ff, new_ff]},
          "released_nets": released, "locked_net_count": len(locked),
          "command": cmd, "exit_code": rc,
          "sha256": {str(path): sha(path) for path in
                     (source, inp, tool, chipdb, xdc, Path(__file__).resolve())}}
if rc == 0:
    result = json.loads((out / "routed.json").read_text())
    routed = result["modules"]["top"]
    actual = routed["cells"]
    record["placements_exact"] = set(actual) == set(cells) and all(
        actual[n]["attributes"].get("NEXTPNR_BEL") == c["attributes"].get("NEXTPNR_BEL")
        for n, c in cells.items())
    record["logical_cells_exact"] = functional_cells(design)[0] == functional_cells(result)[0]
    before_routes, after_routes = routes(module), routes(routed)
    record["retained_routes_exact"] = all(
        (before_routes.get(name, set()) <= after_routes.get(name, set())
         if set(nets[name]["bits"]) & shared_bits else
         before_routes.get(name, set()) == after_routes.get(name, set()))
        for name in locked if name != "$PACKER_GND_NET")
    record["passed"] = all(record[key] for key in
                           ("placements_exact", "logical_cells_exact", "retained_routes_exact"))
    record["fmax_mhz"] = json.loads((out / "report.json").read_text())["fmax"]
(out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({k: v for k, v in record.items() if k not in
                  ("released_nets", "command", "sha256")}, indent=2))
if not record["passed"]:
    raise SystemExit(1)
