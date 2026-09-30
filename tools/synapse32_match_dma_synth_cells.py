#!/usr/bin/env python3
"""Diagnose structural cell reuse across the original and registered-DMA syntheses.

Matches are placement hints only. A later transform must prove logic and routes.
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path):
    return json.loads(path.read_text())["modules"]["kc705_synapse32_top"]


def anchors(old, new):
    names = sorted(set(old["netnames"]) & set(new["netnames"]))
    labels = [defaultdict(set), defaultdict(set)]
    for name in names:
        if name.startswith("$"):
            continue
        a, b = old["netnames"][name]["bits"], new["netnames"][name]["bits"]
        if len(a) != len(b):
            continue
        for i, bits in enumerate((a, b)):
            for index, bit in enumerate(bits):
                labels[i][bit].add(f"net:{name}[{index}]")
    for name in sorted(set(old["ports"]) & set(new["ports"])):
        a, b = old["ports"][name]["bits"], new["ports"][name]["bits"]
        if len(a) != len(b):
            continue
        for i, bits in enumerate((a, b)):
            for index, bit in enumerate(bits):
                labels[i][bit].add(f"port:{name}[{index}]")
    for d in labels:
        for bit in ("0", "1", "x", "z"):
            d[bit].add(f"const:{bit}")
    return labels


def signatures(cells, labels):
    groups = defaultdict(list)
    for name, cell in cells.items():
        ports = tuple(sorted(
            (pin, tuple(tuple(sorted(labels.get(bit, ()))) for bit in bits))
            for pin, bits in cell["connections"].items()
        ))
        key = (cell["type"], json.dumps(cell.get("parameters", {}), sort_keys=True),
               cell.get("attributes", {}).get("src", ""), ports)
        groups[key].append(name)
    return groups


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--old", type=Path, required=True)
    p.add_argument("--new", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    old, new = module(a.old), module(a.new)
    labels = anchors(old, new)
    original_anchors = [len(d) for d in labels]
    matched = {}
    matched_new = set()
    rounds = []
    for step in range(12):
        left = signatures(old["cells"], labels[0])
        right = signatures(new["cells"], labels[1])
        fresh = {}
        for key in left.keys() & right.keys():
            if len(left[key]) == len(right[key]) == 1:
                x, y = left[key][0], right[key][0]
                if x not in matched and y not in matched_new:
                    fresh[x] = y
        if not fresh:
            break
        matched.update(fresh)
        matched_new.update(fresh.values())
        for x, y in fresh.items():
            ca, cb = old["cells"][x], new["cells"][y]
            for pin, bits in ca["connections"].items():
                if pin not in cb["connections"] or len(bits) != len(cb["connections"][pin]):
                    continue
                if ca["port_directions"][pin] != "output":
                    continue
                for i, (bit_a, bit_b) in enumerate(zip(bits, cb["connections"][pin])):
                    label = f"matched:{x}:{pin}[{i}]"
                    labels[0][bit_a].add(label)
                    labels[1][bit_b].add(label)
        rounds.append(len(fresh))
    kind = Counter(old["cells"][x]["type"] for x in matched)
    result = {
        "scope": "Structural placement candidates only; not functional equivalence or a transferable route.",
        "old": str(a.old.resolve()), "new": str(a.new.resolve()),
        "old_cells": len(old["cells"]), "new_cells": len(new["cells"]),
        "initial_anchored_bits": original_anchors, "matched_cells": len(matched),
        "rounds": rounds, "matched_types": dict(kind),
        "sha256": {str(path.resolve()): digest(path) for path in (a.old, a.new, Path(__file__))},
        "matches": matched,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "matches"}, indent=2))


if __name__ == "__main__":
    main()
