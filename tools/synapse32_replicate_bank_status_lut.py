#!/usr/bin/env python3
"""Replicate one unchanged packed LUT for distant low-bank DDR sinks."""
import copy
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from synapse32_locked_reroute_evidence import routes
from synapse32_pinmap_control_audit import functional_cells

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build-grade2-cpu-pe-ddr-write-control-replica/input.json"
OUT = ROOT / "build-grade2-cpu-pe-ddr-bank-status-replica"
ORIGINAL = "$abc$216920$auto$blifparse.cc:557:parse_blif$229060"
REPLICA = "$tiny3tpu$bank_status_low_replica"
BEL = "SLICE_X141Y65/B6LUT"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not OUT.exists()
    design = json.loads(SOURCE.read_text())
    module = design["modules"]["top"]
    cells, nets = module["cells"], module["netnames"]
    parent = cells[ORIGINAL]
    assert parent["type"] == "SLICE_LUTX"
    assert parent["attributes"]["NEXTPNR_BEL"] == "SLICE_X130Y132/B6LUT"
    assert not parent["attributes"].get("CONSTR_PARENT")
    assert parent["attributes"].get("CONSTR_CHILDREN") == "$auto$ff.cc:337:slice$68090"
    assert REPLICA not in cells and REPLICA not in nets
    assert all(c["attributes"].get("NEXTPNR_BEL") != BEL for c in cells.values())
    old_bit = parent["connections"]["O6"][0]
    fresh_bit = max(
        b for c in cells.values() for bs in c["connections"].values() for b in bs if isinstance(b, int)
    ) + 1
    selected = []
    for name, cell in cells.items():
        if name == ORIGINAL:
            continue
        inputs = [pin for pin, bs in cell["connections"].items()
                  if cell["port_directions"][pin] == "input" and old_bit in bs]
        if not inputs:
            continue
        bel = cell["attributes"].get("NEXTPNR_BEL", "")
        match = re.search(r"SLICE_X(\d+)Y(\d+)/", bel)
        if not match or not (137 <= int(match[1]) <= 149 and int(match[2]) <= 70):
            continue
        for pin in inputs:
            cell["connections"][pin] = [fresh_bit if b == old_bit else b
                                         for b in cell["connections"][pin]]
        selected.append((name, inputs, bel))
    assert len(selected) == 7
    assert any(name == "$auto$ff.cc:337:slice$68394" for name, _, _ in selected)
    clone = copy.deepcopy(parent)
    clone["attributes"]["NEXTPNR_BEL"] = BEL
    clone["attributes"].pop("CONSTR_CHILDREN")
    clone["connections"]["O6"] = [fresh_bit]
    cells[REPLICA] = clone
    nets[REPLICA] = {"hide_name": 1, "bits": [fresh_bit], "attributes": {}}
    # Exact structural check: undo the fanout split and remove the identical
    # copy, then recover every original functional cell and connection.
    restored = copy.deepcopy(design)
    rmodule = restored["modules"]["top"]
    del rmodule["cells"][REPLICA]
    del rmodule["netnames"][REPLICA]
    for name, inputs, _ in selected:
        for pin in inputs:
            rmodule["cells"][name]["connections"][pin] = [
                old_bit if b == fresh_bit else b
                for b in rmodule["cells"][name]["connections"][pin]
            ]
    original = json.loads(SOURCE.read_text())
    assert functional_cells(restored)[0] == functional_cells(original)[0]
    assert clone["parameters"] == parent["parameters"]
    assert all(clone["connections"][p] == parent["connections"][p]
               for p in parent["connections"] if p != "O6")
    released, locked = [], []
    for name, net in nets.items():
        attrs = net.get("attributes", {})
        route = attrs.get("ROUTING", "")
        if old_bit in net["bits"]:
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
    OUT.mkdir()
    inp = OUT / "input.json"
    inp.write_text(json.dumps(design, separators=(",", ":")) + "\n")
    tool = Path("/tmp/tiny3tpu-nextpnr-placement-label-replay/nextpnr-xilinx")
    chipdb = Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin")
    xdc = (ROOT / "build-grade2-pre-fixup-routing-control/restored-clocks.xdc").resolve()
    cmd = [str(tool), "--chipdb", str(chipdb), "--xdc", str(xdc), "--freq", "100",
           "--seed", "5", "--json", str(inp), "--write", str(OUT / "routed.json"),
           "--report", str(OUT / "report.json"), "--log", str(OUT / "route.log"),
           "--no-pack", "--placer", "sa", "--starttemp", "0"]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NEXTPNR_", "TINY3TPU_"))}
    env.update(TINY3TPU_REPLAY_PLACEMENT_LABELS="1", TINY3TPU_LOSSLESS_ROUTE_NAMES="1",
               TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS="1",
               TINY3TPU_TIMING_GRAPH=str(OUT / "timing-graph.tsv"))
    with (OUT / "console.log").open("w") as log:
        rc = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    record = {"passed": False, "kind": "exact_lut_copy_local_fanout_split",
              "source": str(SOURCE), "original": ORIGINAL, "replica": REPLICA,
              "replica_bel": BEL, "selected_sinks": selected, "released_nets": released,
              "locked_net_count": len(locked), "command": cmd, "exit_code": rc,
              "sha256": {str(p): digest(p) for p in (SOURCE, inp, tool, chipdb, xdc, Path(__file__))}}
    if rc == 0:
        result = json.loads((OUT / "routed.json").read_text())
        actual = result["modules"]["top"]
        record["placements_exact"] = set(actual["cells"]) == set(cells) and all(
            actual["cells"][n]["attributes"].get("NEXTPNR_BEL") == c["attributes"].get("NEXTPNR_BEL")
            for n, c in cells.items())
        record["logical_cells_exact"] = functional_cells(design)[0] == functional_cells(result)[0]
        before, after = routes(module), routes(actual)
        record["retained_routes_monotonic"] = all(
            before.get(name, set()) <= after.get(name, set()) for name in locked
            if name != "$PACKER_GND_NET")
        record["passed"] = all(record[k] for k in
                               ("placements_exact", "logical_cells_exact", "retained_routes_monotonic"))
        record["fmax_mhz"] = json.loads((OUT / "report.json").read_text())["fmax"]
    (OUT / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: v for k, v in record.items()
                      if k not in ("selected_sinks", "released_nets", "sha256", "command")}, indent=2))
    if not record["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
