#!/usr/bin/env python3
"""Correct nextpnr's implicit internal VREF for KC705's externally supplied banks.

UG810 requires the external 0.75 V VTTREF on banks 32/34. The current backend
unconditionally emits VREF.V_675_MV for SSTL inputs, even without INTERNAL_VREF
in XDC. These database features enable INTERNAL_VREF (prjxray 030-iob18).
Remove only those two features, retaining the original FASM and an audit record.
No placement, routing, memory contents, clocks, or termination bits are changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def corrected_fasm(source, tiles):
    expected = {tile + ".VREF.V_675_MV" for tile in tiles}
    actual = {line.strip() for line in source.splitlines()
              if re.search(r"\.VREF\.V_[0-9]+_MV", line) and not line.lstrip().startswith("#")}
    if actual != expected:
        raise ValueError("Unexpected internal VREF features: " + repr(sorted(actual)))
    lines = [line for line in source.splitlines() if line.strip() not in expected]
    return "\n".join(lines) + "\n", sorted(expected)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--db-root", type=Path, required=True)
    a = p.parse_args()
    build, db = a.build_dir.resolve(), a.db_root.resolve()
    profile = json.loads((build/"io-profile.json").read_text())
    if not profile["ddr_enabled"] or profile["profile"] != "experimental-sstl15":
        p.error("Correction is restricted to the explicit KC705 SSTL15 experiment")
    xdc = (build/"kc705.xdc").read_text()
    if "INTERNAL_VREF" in xdc or len(re.findall(r"IOSTANDARD SSTL15 \[get_ports \{ddram_dq\[\d+\]\}\]", xdc)) != 64:
        p.error("Unexpected DDR input constraints")
    partfile = db/"xc7k325tffg900-2/part.json"
    part = json.loads(partfile.read_text())
    tiles = ["HCLK_IOI_" + part["iobanks"][str(n)] for n in (32, 34)]
    raw, fasm, record = build/"soc-internal-vref.fasm", build/"soc.fasm", build/"external-vref.json"
    if raw.exists() or record.exists():
        p.error("Correction already recorded; do not overwrite its evidence")
    source = fasm.read_text()
    corrected, removed = corrected_fasm(source, tiles)
    raw.write_text(source)
    fasm.write_text(corrected)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    record.write_text(json.dumps({
        "external_vref_volts": 0.75, "banks": [32, 34], "hclk_tiles": tiles,
        "removed_features": removed, "only_these_features_removed": True,
        "board_reference": "https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content",
        "feature_reference": "https://github.com/f4pga/prjxray/blob/master/fuzzers/030-iob18/generate.py",
        "sha256": {str(path): digest(path) for path in (raw, fasm, partfile, Path(__file__).resolve())},
    }, indent=2)+"\n")
    print("Corrected KC705 external 0.75 V VREF:", ", ".join(removed))


if __name__ == "__main__":
    main()
