#!/usr/bin/env python3
"""Bind the improved retained route to a readback-checked experimental bitstream."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "build-grade2-cpu-pe-ddr-capture-pair-x119y40"
BIT = ROOT / "build-grade2-cpu-pe-ddr-capture-pair-x119y40-bit"
PART = "xc7k325tffg900-2"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    proof_dirs = [
        "build-grade2-incremental-cq-cpu-divider-hydrated-plus-tpu-input-ff",
        "build-grade2-cpu-pe-ddr-reset-lut-y12-mapped",
        "build-grade2-cpu-pe-ddr-write-control-replica",
        "build-grade2-cpu-pe-ddr-bank-status-replica",
        "build-grade2-cpu-pe-ddr-capture-pair-x119y40-mapped",
    ]
    proofs = [ROOT / name / "manifest.json" for name in proof_dirs]
    assert all(json.loads(path.read_text())["passed"] for path in proofs)
    route_manifest = json.loads((ROUTE / "manifest.json").read_text())
    assert route_manifest["exit_code"] == 0
    assert route_manifest["placements_exact"] and route_manifest["logical_cells_exact"]
    assert (ROUTE / "routed.json").read_bytes() == (BIT / "export-routed.json").read_bytes()
    report = json.loads((BIT / "export-report.json").read_text())
    assert report["fmax"]["clk"]["achieved"] >= 100
    assert report["fmax"]["soc.cpu_clk"]["achieved"] >= 100
    files = proofs + [ROUTE / "manifest.json", ROUTE / "routed.json"] + [
        BIT / name for name in ("export-routed.json", "export-report.json", "latest.fasm",
                                "latest.frames", "latest.bit", "roundtrip.frames",
                                "export-route.log", "fasm2frames.log", "frames2bit.log", "bitread.log")
    ] + [ROOT / "build-toolchain-recovery/kc705-frame-db-kc705.tar.gz",
         Path("/tmp/tiny3tpu-kc705-frame-db/kintex7") / PART / "part.yaml",
         Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin"),
         Path("/tmp/tiny3tpu-nextpnr-placement-label-replay/nextpnr-xilinx"),
         Path(__file__).resolve()]
    historical = json.loads((ROOT / "build-grade2-incremental-cq-tpu-output-pairs-bit/manifest.json").read_text())
    for path in files[-5:-1]:
        assert digest(path) == historical["sha256"][str(path)], path
    for path in (BIT / "fasm2frames.log", BIT / "frames2bit.log", BIT / "bitread.log"):
        assert "error" not in path.read_text().lower(), path
    assert "DONE" in (BIT / "bitread.log").read_text()
    image = (BIT / "latest.bit").read_bytes()
    assert image.count(bytes.fromhex("aa995566")) == 1 and PART.encode() in image
    expected = {}
    for line in (BIT / "latest.frames").open():
        addr, words = line.split(" ", 1)
        expected[int(addr, 16)] = [int(word, 16) for word in words.strip().split(",")]
    actual = {}
    addr, words = None, []
    for line in (BIT / "roundtrip.frames").open():
        if line.startswith(".frame "):
            if addr is not None:
                actual[addr] = words
            addr, words = int(line.split()[1], 16), []
        elif line.strip():
            words.extend(int(word, 16) for word in line.split())
    if addr is not None:
        actual[addr] = words
    assert set(expected) <= set(actual)
    assert all(len(words) == 101 for words in expected.values())
    assert all(len(words) == 101 for words in actual.values())
    extra = set(actual) - set(expected)
    assert all(all(word == 0 for i, word in enumerate(actual[k]) if i != 50) for k in extra)
    assert all(all(value == actual[k][i] for i, value in enumerate(words) if i != 50)
               for k, words in expected.items())
    record = {
        "passed": True, "part": PART, "route": str(ROUTE.relative_to(ROOT)),
        "bitstream": str((BIT / "latest.bit").relative_to(ROOT)),
        "size_bytes": len(image), "input_frames": len(expected),
        "readback_frames": len(actual), "added_zero_data_frames": len(extra),
        "ecc_word_index": 50, "all_non_ecc_frame_words_exact": True,
        "reroute_byte_identical": True, "route_logic_and_monotonic_audits_passed": True,
        "native_fmax_mhz": {k: v["achieved"] for k, v in report["fmax"].items()},
        "physical_100mhz_accepted": False, "hardware_tested": False,
        "scope": "Open-source bitstream export and frame readback for a diagnostic route. "
                 "Mapped setup exceeds 10 ns; primitive/IO, skew and hold coverage is incomplete.",
        "sha256": {str(path): digest(path) for path in files},
    }
    out = BIT / "manifest.json"
    assert not out.exists()
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k != "sha256"}, indent=2))


if __name__ == "__main__":
    main()
