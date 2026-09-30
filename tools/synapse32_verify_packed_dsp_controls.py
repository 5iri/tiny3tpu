#!/usr/bin/env python3
"""Check that DSP constant-pin inversion preserves the PE's logical mode."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--synth", type=Path, required=True)
parser.add_argument("--packed", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
a = parser.parse_args()
original = json.loads(a.synth.read_text())["modules"]["kc705_synapse32_top"]["cells"]
packed = json.loads(a.packed.read_text())["modules"]["top"]["cells"]
drivers = {bit: cell["type"] for cell in packed.values()
           for port, bits in cell["connections"].items()
           if cell["port_directions"].get(port) == "output" for bit in bits}


def effective(cell, pin):
    wire = cell["connections"].get(pin)
    if wire and drivers.get(wire[0]) in ("PSEUDO_GND", "PSEUDO_VCC"):
        value = int(drivers[wire[0]] == "PSEUDO_VCC")
    elif f" {pin} " in " " + cell["attributes"].get("DSP_GND_PINS", "") + " ":
        value = 0
    elif f" {pin} " in " " + cell["attributes"].get("DSP_VCC_PINS", "") + " ":
        value = 1
    else:
        raise AssertionError(f"{pin} is not a constant")
    boundary = len(pin)
    while boundary and pin[boundary - 1].isdigit():
        boundary -= 1
    bus, index = pin[:boundary], pin[boundary:]
    if index:
        value ^= (int(cell["parameters"].get(f"IS_{bus}_INVERTED", "0"), 2) >> int(index)) & 1
        value ^= int(cell["parameters"].get(f"IS_{bus}[{index}]_INVERTED", "0"), 2) & 1
    else:
        value ^= int(cell["parameters"].get(f"IS_{bus}_INVERTED", "0"), 2) & 1
    return value


groups = {"OPMODE": 7, "ALUMODE": 4, "INMODE": 5, "CARRYINSEL": 3, "CARRYIN": 1}
checked = 0
for name, gate in packed.items():
    if gate["type"] != "DSP48E1_DSP48E1" or ".PE." not in name:
        continue
    source = original[name]
    assert source["type"] == "DSP48E1" and int(source["parameters"]["PREG"], 2) == 1
    for group, width in groups.items():
        expected = source["connections"][group]
        assert len(expected) == width
        for bit in range(width):
            pin = group if width == 1 else f"{group}{bit}"
            assert effective(gate, pin) == int(expected[bit]), (name, pin)
    checked += 1
assert checked == 32, checked
result = {"passed": True, "registered_pe_dsps": checked,
          "sha256": {str(path.resolve()): sha(path) for path in (a.synth, a.packed, Path(__file__))}}
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(result, indent=2) + "\n")
print(f"PASS effective packed controls for {checked} registered PE DSPs")
