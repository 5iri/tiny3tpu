#!/usr/bin/env python3
"""Try one zero-logic-change FF move on the retained routed KC705 design."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from synapse32_pinmap_control_audit import functional_cells
from synapse32_locked_reroute_evidence import routes


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--cell", required=True)
parser.add_argument("--bel", required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
source, out = args.source.resolve(), args.out.resolve()
if out.exists():
    raise SystemExit("Output directory already exists")
gate = json.loads(source.read_text())
module = gate["modules"]["top"]
cells, nets = module["cells"], module["netnames"]
cell = cells[args.cell]
assert cell["type"] == "SLICE_FFX" and not cell["attributes"].get("CONSTR_PARENT")
old = cell["attributes"]["NEXTPNR_BEL"]
assert old != args.bel and args.bel.endswith("/C5FF")
assert all(c["attributes"].get("NEXTPNR_BEL") != args.bel for c in cells.values())
cell["attributes"]["NEXTPNR_BEL"] = args.bel
changed_bits = set(cell["connections"]["Q"])
shared_bits = {b for pin in ("D", "CK", "SR") for b in cell["connections"].get(pin, [])}
released = []
locked = []
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
inp.write_text(json.dumps(gate, separators=(",", ":")) + "\n")
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
record = {
    "passed": False,
    "source": str(source),
    "move": {args.cell: [old, args.bel]},
    "released_nets": released,
    "locked_net_count": len(locked),
    "command": cmd,
    "exit_code": rc,
    "sha256": {str(p): digest(p) for p in (source, inp, tool, chipdb, xdc, Path(__file__).resolve())},
}
if rc == 0:
    result = json.loads((out / "routed.json").read_text())
    routed = result["modules"]["top"]
    actual = routed["cells"]
    record["placements_exact"] = set(actual) == set(cells) and all(
        actual[n]["attributes"].get("NEXTPNR_BEL") == c["attributes"].get("NEXTPNR_BEL") for n, c in cells.items()
    )
    record["logical_cells_exact"] = functional_cells(gate)[0] == functional_cells(result)[0]
    before_routes, after_routes = routes(module), routes(routed)
    record["retained_routes_exact"] = all(
        (before_routes.get(name, set()) <= after_routes.get(name, set())
         if set(nets[name]["bits"]) & shared_bits else
         before_routes.get(name, set()) == after_routes.get(name, set()))
        for name in locked if name != "$PACKER_GND_NET"
    )
    record["passed"] = all(record[k] for k in
                           ("placements_exact", "logical_cells_exact", "retained_routes_exact"))
    record["fmax_mhz"] = json.loads((out / "report.json").read_text())["fmax"]
(out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({k: v for k, v in record.items() if k not in ("released_nets", "sha256", "command")}, indent=2))
if not record["passed"]:
    raise SystemExit(1)
