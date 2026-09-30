#!/usr/bin/env python3
"""Try explicit early occupancy predicates with unchanged late controls."""
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
    text = source.read_text()
    declaration = "reg     [4:0] main_write_w_buffer_level2 = 5'd0;"
    assert text.count(declaration) == 1
    extra = """reg     [4:0] main_write_w_buffer_level2 = 5'd0;
(* keep = 1 *) wire [4:0] main_write_w_buffer_level2_inc_pred = {
    (&main_write_w_buffer_level2[3:0]), (&main_write_w_buffer_level2[2:0]),
    (&main_write_w_buffer_level2[1:0]), main_write_w_buffer_level2[0], 1'b1};
(* keep = 1 *) wire [4:0] main_write_w_buffer_level2_dec_pred = {
    !(|main_write_w_buffer_level2[3:0]), !(|main_write_w_buffer_level2[2:0]),
    !(|main_write_w_buffer_level2[1:0]), !main_write_w_buffer_level2[0], 1'b1};
wire main_write_w_buffer_level2_inc_en = main_write_w_buffer_queue && !main_write_w_buffer_dequeue;
wire main_write_w_buffer_level2_dec_en = !main_write_w_buffer_queue && main_write_w_buffer_dequeue;"""
    text = text.replace(declaration, extra)
    source_lines = source.read_text().splitlines(keepends=True)
    old = [line for line in source_lines if line.startswith("    main_write_w_buffer_level2[") and " <= " in line]
    assert len(old) == 5 and all(f"[{i}]" in old[i] for i in range(5))
    start = text.index(old[0]);end = text.index(old[-1], start) + len(old[-1])
    replacement = "".join(
        f"    main_write_w_buffer_level2[{i}] <= main_write_w_buffer_level2[{i}] ^ "
        f"((main_write_w_buffer_level2_inc_en && main_write_w_buffer_level2_inc_pred[{i}]) || "
        f"(main_write_w_buffer_level2_dec_en && main_write_w_buffer_level2_dec_pred[{i}]));\n"
        for i in range(5))
    assert text[start:end] == "".join(old)
    text = text[:start] + replacement + text[end:]
    for level in range(32):
        for queue in (0, 1):
            for dequeue in (0, 1):
                up, down = queue and not dequeue, dequeue and not queue
                trial = level
                for i in range(5):
                    mask = (1 << i) - 1
                    inc = (level & mask) == mask
                    dec = (level & mask) == 0
                    trial ^= int(bool((up and inc) or (down and dec))) << i
                expected = (level + int(up) - int(down)) & 31
                assert trial == expected, (level, queue, dequeue)
    out.mkdir()
    target = out / "kc705_dram.v"
    target.write_text(text)
    record = {"passed": True, "scope": "Isolated generated-LiteDRAM RTL trial; all 128 local occupancy transitions match. Full SoC behavior and timing pending.",
              "source": str(source), "target": str(target), "cases": 128,
              "sha256": {str(q): sha(q) for q in (source, target, Path(__file__).resolve())}}
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k != "sha256"}, indent=2))


if __name__ == "__main__":
    main()
