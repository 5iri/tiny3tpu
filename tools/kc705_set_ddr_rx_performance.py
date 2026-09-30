#!/usr/bin/env python3
"""Explicit KC705 experiment: set IBUF_LOW_PWR=FALSE on exactly 64 DQ pads.

The current nextpnr backend does not emit the single-ended ZIBUF_LOW_PWR
feature. This changes only that documented input-buffer performance setting;
it leaves output drive, voltage, termination, routing and clocks unchanged.
Run before the external-VREF correction and the strict bitstream export.
"""
import argparse
import hashlib
import json
from pathlib import Path


def dq_features(routed, grid):
    cells = next(iter(routed["modules"].values()))["cells"]
    sites = {site: (tile, kind) for tile, info in grid.items()
             for site, kind in info.get("sites", {}).items()}
    features = {}
    for n in range(64):
        name = f"ddram_dq[{n}]"
        pad = cells[name]
        attrs = pad["attributes"]
        assert pad["type"] == "PAD" and attrs["IOSTANDARD"] == "SSTL15"
        assert attrs["X_IO_DIR"] == "INOUT"
        tile, kind = sites[attrs["NEXTPNR_BEL"].split("/")[0]]
        assert grid[tile]["type"] == "RIOB18" and kind in ("IOB18M", "IOB18S")
        features[name] = f"{tile}.IOB_Y{0 if kind == 'IOB18M' else 1}.ZIBUF_LOW_PWR"
    assert len(set(features.values())) == 64
    return features


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--db-root", type=Path, required=True)
    a = p.parse_args()
    out, db = a.build_dir.resolve(), a.db_root.resolve()
    profile_path = out / "io-profile.json"
    profile = json.loads(profile_path.read_text())
    assert profile["ddr_enabled"] and profile["profile"] == "experimental-sstl15"
    record = out / "rx-performance.json"
    before, after = out / "before-rx-performance.fasm", out / "rx-performance.fasm"
    assert not any(f.exists() for f in (record, before, after, out / "external-vref.json"))
    grid_path = db / "xc7k325t/tilegrid.json"
    routed_path = out / "soc_routed.json"
    features = dq_features(json.loads(routed_path.read_text()), json.loads(grid_path.read_text()))
    source = (out / "soc.fasm").read_text()
    lines = set(line.strip() for line in source.splitlines())
    for feature in features.values():
        assert feature not in lines
        assert feature.replace("ZIBUF_LOW_PWR", "SSTL12_SSTL135_SSTL15.IN") in lines
    result = source.rstrip() + "\n\n# Explicit DDR DQ IBUF_LOW_PWR=FALSE experiment\n"
    result += "\n".join(sorted(features.values())) + "\n"
    before.write_text(source)
    after.write_text(result)
    (out / "soc.fasm").write_text(result)
    profile["dq_input_buffer_low_power"] = False
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")
    record.write_text(json.dumps({
        "experimental": True, "input_buffer_low_power": False,
        "only_added_features": features,
        "reference": "https://docs.amd.com/r/en-US/ug953-vivado-7series-libraries/IOBUF",
        "sha256": {str(f): hashlib.sha256(f.read_bytes()).hexdigest()
                   for f in (before, after, routed_path, grid_path, profile_path, Path(__file__).resolve())}
    }, indent=2) + "\n")
    print("Set IBUF_LOW_PWR=FALSE on exactly 64 DDR DQ inputs; no other features changed")


if __name__ == "__main__":
    main()
