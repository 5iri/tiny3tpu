#!/usr/bin/env python3
"""Explicit diagnostic: replace implicit 0.675 V with nominal internal 0.75 V.

This is separate from the normal external-reference correction. UG471 permits
internal 0.75 V for SSTL15; the VREF pads become ordinary unused I/O. No pad is
driven by this experiment, and the board's external reference remains intact.
"""
import argparse
import hashlib
import json
from pathlib import Path
from kc705_fix_external_vref import corrected_fasm


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--db-root", type=Path, required=True)
    a = p.parse_args()
    out, db = a.build_dir.resolve(), a.db_root.resolve()
    profile_path = out / "io-profile.json"
    profile = json.loads(profile_path.read_text())
    assert profile["ddr_enabled"] and profile["profile"] == "experimental-sstl15"
    record, raw = out / "internal-vref.json", out / "soc-implicit-vref.fasm"
    assert not any(f.exists() for f in (record, raw, out / "external-vref.json"))
    part_path = db / "xc7k325tffg900-2/part.json"
    part = json.loads(part_path.read_text())
    tiles = ["HCLK_IOI_" + part["iobanks"][str(n)] for n in (32, 34)]
    fasm = out / "soc.fasm"
    source = fasm.read_text()
    corrected, removed = corrected_fasm(source, tiles)
    added = sorted(t + ".VREF.V_750_MV" for t in tiles)
    raw.write_text(source)
    fasm.write_text(corrected + "\n".join(added) + "\n")
    profile["fpga_vref_source"] = "internal"
    profile["fpga_vref_volts"] = 0.75
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")
    record.write_text(json.dumps({
        "experimental": True, "internal_vref_volts": 0.75, "banks": [32, 34],
        "removed_features": removed, "added_features": added,
        "reference": "https://docs.amd.com/api/khub/documents/IbGcnPFe6eF19RHma_Y~IA/content",
        "sha256": {str(f): hashlib.sha256(f.read_bytes()).hexdigest()
                   for f in (raw, fasm, part_path, Path(__file__).resolve())}
    }, indent=2) + "\n")
    print("DIAGNOSTIC: internal SSTL15 VREF 0.75 V on banks 32/34; no pad outputs changed")


if __name__ == "__main__":
    main()
