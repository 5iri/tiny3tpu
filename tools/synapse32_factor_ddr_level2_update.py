#!/usr/bin/env python3
"""Make an isolated, cycle-equivalent LiteDRAM level-2 counter timing trial."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    source, out = a.source.resolve(), a.out.resolve()
    assert not out.exists()
    original = source.read_text()
    lines = [f"    main_write_w_buffer_level2[{i}] <= " for i in range(5)]
    start = original.index(lines[0])
    end = original.index("\n", original.index(lines[-1], start)) + 1
    block = original[start:end]
    assert all(block.count(prefix) == 1 for prefix in lines)
    assert block.count("\n") == 5
    replacement = "    main_write_w_buffer_level2 <= main_write_w_buffer_level2_next;\n"
    before = "reg     [4:0] main_write_w_buffer_level2 = 5'd0;"
    assert original.count(before) == 1
    declaration = """reg     [4:0] main_write_w_buffer_level2 = 5'd0;
// Compute both occupancy candidates before the late queue/dequeue decision.
wire [4:0] main_write_w_buffer_level2_inc = main_write_w_buffer_level2 + 5'd1;
wire [4:0] main_write_w_buffer_level2_dec = main_write_w_buffer_level2 - 5'd1;
wire [4:0] main_write_w_buffer_level2_next =
    (main_write_w_buffer_queue && !main_write_w_buffer_dequeue) ? main_write_w_buffer_level2_inc :
    (!main_write_w_buffer_queue && main_write_w_buffer_dequeue) ? main_write_w_buffer_level2_dec :
    main_write_w_buffer_level2;"""
    candidate = original.replace(before, declaration).replace(block, replacement)
    assert candidate != original
    assert candidate.replace(declaration, before).replace(replacement, block) == original
    # Exhaust the full local state/control transition, including simultaneous controls.
    for level in range(32):
        for queue in (0, 1):
            for dequeue in (0, 1):
                old = level
                for bit in range(5):
                    if bit == 0:
                        toggle = queue ^ dequeue
                    else:
                        low = level & ((1 << bit) - 1)
                        toggle = ((queue and not dequeue and low == (1 << bit) - 1) or
                                  (not queue and dequeue and low == 0))
                    old ^= int(bool(toggle)) << bit
                new = ((level + 1) & 31 if queue and not dequeue else
                       ((level - 1) & 31 if not queue and dequeue else level))
                assert old == new, (level, queue, dequeue)
    out.mkdir()
    target = out / "kc705_dram.v"
    target.write_text(candidate)
    record = {"passed": True, "scope": "Isolated generated-LiteDRAM RTL trial; all 128 counter state/control cases are equivalent. Full SoC behavior and timing are not yet proven.",
              "source": str(source), "target": str(target), "cases": 128,
              "sha256": {str(q): sha(q) for q in (source, target, Path(__file__).resolve())}}
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k != "sha256"}, indent=2))


if __name__ == "__main__":
    main()
