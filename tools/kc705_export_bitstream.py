#!/usr/bin/env python3
"""Export a checked KC705 route and verify the bitstream file's frame roundtrip.

Does not program hardware. This checks file integrity, not complete timing or
electrical correctness; the openXC7 timing model still has coverage limitations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from kc705_open_build import validate_route_log


def frame_data_word(index, value):
    # X-Ray xc7series/ecc.cc: only bits 12:0 of word 50 are generated ECC.
    # Upper bits include HCLK configuration (including INTERNAL_VREF).
    return value & (0xffffe000 if index == 50 else 0xffffffff)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--db-root", type=Path, required=True, help="Kintex7 frame database directory")
    p.add_argument("--tools", type=Path, default=Path.home() / ".apio/packages/openxc7/bin")
    a = p.parse_args()
    out = a.build_dir.resolve()
    db = a.db_root.resolve()
    part = "xc7k325tffg900-2"
    route = (out / "route.log").read_text()
    validate_route_log(route)
    hardware_manifest = out / "hardware-manifest.json"
    hardware_only = hardware_manifest.exists()
    hardware_source = json.loads(hardware_manifest.read_text()) if hardware_only else None
    if hardware_only:
        if (hardware_source.get("target") != "kc705_uberddr3" or
                hardware_source.get("cpu") or hardware_source.get("firmware") or
                hardware_source.get("tpu") or hardware_source.get("dma") or
                hardware_source.get("ethernet")):
            raise ValueError("Unsupported or connected hardware-only target manifest")
        for source, expected_hash in hardware_source["sha256"].items():
            if hashlib.sha256(Path(source).read_bytes()).hexdigest() != expected_hash:
                raise ValueError("Hardware source changed since route: " + source)
    io_profile = out / "io-profile.json"
    profile = json.loads(io_profile.read_text()) if io_profile.exists() else None
    vref_record = out / "external-vref.json"
    internal_vref = bool(profile and profile.get("fpga_vref_source") == "internal")
    if internal_vref:
        assert profile["profile"] == "experimental-sstl15" and profile["fpga_vref_volts"] == 0.75
        vref_record = out / "internal-vref.json"
    boot_patch_record = out / "patch.json"
    rx_record = out / "rx-performance.json"
    rx_features = {}
    if profile and profile.get("dq_input_buffer_low_power") is False:
        rx = json.loads(rx_record.read_text())
        assert rx["input_buffer_low_power"] is False
        for path, expected_hash in rx["sha256"].items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected_hash, path
        from kc705_set_ddr_rx_performance import dq_features
        rx_features = dq_features(json.loads((out / "soc_routed.json").read_text()),
            json.loads((db / "xc7k325t/tilegrid.json").read_text()))
        assert rx_features == rx["only_added_features"]
        active = lambda p: {s.strip() for s in p.read_text().splitlines()
                            if s.strip() and not s.lstrip().startswith("#")}
        before = active(out / "before-rx-performance.fasm")
        after = active(out / "rx-performance.fasm")
        assert after - before == set(rx_features.values()) and not before - after
        assert set(rx_features.values()) <= active(out / "soc.fasm")
    if boot_patch_record.exists():
        boot_patch = json.loads(boot_patch_record.read_text())
        assert boot_patch["passed"] and boot_patch["route_unchanged"]
        assert boot_patch["full_64k_fasm_reconstruction_exact"]
        assert boot_patch["all_non_boot_init_features_unchanged"]
        for path, expected_hash in boot_patch["sha256"].items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected_hash, path
    if profile and profile["ddr_enabled"]:
        if internal_vref:
            part_info = json.loads((db / part / "part.json").read_text())
            expected = {"HCLK_IOI_" + part_info["iobanks"][str(n)] + ".VREF.V_750_MV" for n in (32, 34)}
            present = {s.strip() for s in (out / "soc.fasm").read_text().splitlines()
                       if ".VREF.V_" in s and not s.lstrip().startswith("#")}
            assert present == expected
        elif ".VREF.V_" in (out / "soc.fasm").read_text():
            raise ValueError("KC705 DDR banks require external VREF; run kc705_fix_external_vref.py")
        if profile["profile"] == "experimental-sstl15":
            vref = json.loads(vref_record.read_text())
            for path, expected_hash in vref["sha256"].items():
                assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected_hash, path

    def run(name, args):
        with (out / (name + ".log")).open("w") as log:
            subprocess.run(list(map(str, args)), stdout=log, stderr=subprocess.STDOUT, check=True)

    run("fasm2frames", [a.tools / "fasm2frames", "--db-root", db, "--part", part,
                       out / "soc.fasm", out / "soc.frames"])
    run("frames2bit", [a.tools / "xc7frames2bit", "--part_file", db / part / "part.yaml",
                      "--part_name", part, "--frm_file", out / "soc.frames",
                      "--output_file", out / "soc.bit"])
    run("bitread", [a.tools / "bitread", "--part_file", db / part / "part.yaml",
                    "-o", out / "roundtrip.frames", out / "soc.bit"])
    expected = {}
    for line in (out / "soc.frames").open():
        addr, words = line.split(" ", 1)
        expected[int(addr, 16)] = [int(x, 16) for x in words.strip().split(",")]
    actual, addr, words = {}, None, []
    for line in (out / "roundtrip.frames").open():
        if line.startswith(".frame "):
            if addr is not None:
                actual[addr] = words
            addr, words = int(line.split()[1], 16), []
        elif line.strip():
            words.extend(int(x, 16) for x in line.split())
    if addr is not None:
        actual[addr] = words
    assert set(expected) <= set(actual)
    assert all(len(w) == 101 for w in actual.values())
    assert all(all(frame_data_word(i,x) == frame_data_word(i,actual[a][i])
                   for i, x in enumerate(w)) for a, w in expected.items())
    assert all(all(frame_data_word(i,x) == 0 for i, x in enumerate(actual[a]))
               for a in set(actual) - set(expected))
    if profile and profile["ddr_enabled"]:
        grid = json.loads((db / "xc7k325t/tilegrid.json").read_text())
        segbits = dict(line.split(maxsplit=1) for line in
                       (db / "segbits_riob18.db").read_text().splitlines())
        for feature in rx_features.values():
            tile, local = feature.split(".", 1)
            mapping = grid[tile]["bits"]["CLB_IO_CLK"]
            for bit in segbits["RIOB18." + local].split():
                assert not bit.startswith("!")
                frame, offset = map(int, bit.split("_"))
                assert actual[int(mapping["baseaddr"], 16) + frame][mapping["offset"] + offset // 32] & (1 << (offset % 32))
        part_info = json.loads((db / part / "part.json").read_text())
        for tile in ["HCLK_IOI_" + part_info["iobanks"][str(n)] for n in (32, 34)]:
            bits = grid[tile]["bits"]["CLB_IO_CLK"]
            assert grid[tile]["type"] == "HCLK_IOI"
            # segbits_hclk_ioi.db: internal VREF enable is frame +40, bit 19;
            # the four selectable voltages use bits 25 through 28.
            addr = int(bits["baseaddr"],16) + 40
            expected_vref = (1<<19) | (1<<26) if internal_vref else 0
            assert actual[addr][bits["offset"]] & ((1<<19) | (15<<25)) == expected_vref
    clocks = {}
    for name, achieved, target in re.findall(
            r"Max frequency for clock\s+'([^']+)': ([0-9.]+) MHz \(PASS at ([0-9.]+) MHz\)", route):
        clocks[name] = dict(achieved_mhz=float(achieved), target_mhz=float(target))
    image_files = ["soc.json", "soc_routed.json", "soc.fasm"]
    if not hardware_only:
        image_files.append("firmware.hex")
    image_files += ["soc.bit", "soc.frames", "roundtrip.frames", "route.log",
                    "kc705.xdc", "clocks.py"]
    files = [out / n for n in image_files]
    # Hash the exact configuration database used to encode the FASM. A
    # different database can route the same design but lack frame mappings.
    database_files = [db / part / "part.yaml", db / part / "part.json",
                      db / "xc7k325t/tilegrid.json", db / "segbits_riob18.db",
                      db / "segbits_int_r.db", db / "segbits_hclk_ioi.db"]
    files += database_files + [Path(__file__).resolve()]
    if hardware_only:
        files += [hardware_manifest]
    timing_report = out / "timing-report.json"
    if timing_report.exists():
        files += [timing_report]
    if io_profile.exists():
        files += [io_profile]
    if vref_record.exists():
        files += [vref_record, out / ("soc-implicit-vref.fasm" if internal_vref else "soc-internal-vref.fasm")]
    if boot_patch_record.exists():
        files += [boot_patch_record, out / "patched.fasm"]
    if rx_features:
        files += [rx_record, out / "before-rx-performance.fasm", out / "rx-performance.fasm",
                  Path(__file__).resolve().with_name("kc705_set_ddr_rx_performance.py")]
    record = dict(passed=True, part=part, frame_roundtrip_exact_except_generated_ecc=True,
                  complete_physical_timing_proven=False, clocks=clocks,
                  frame_database=str(db),
                  ecc_exclusion="word 50 bits 12:0 only",
                  dsp_preg_profiles_timed=route.count("DSP_PREG_TIMED "),
                  io_profile=profile,
                  sha256={str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files})
    (out / "bitstream-manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print("PASS bitstream frame roundtrip:", len(expected), "input frames; clocks:", clocks)


if __name__ == "__main__":
    main()
