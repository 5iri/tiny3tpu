#!/usr/bin/env python3
"""Simulate the real hardware engine with stalled CSR/DRAM targets and faults.

This deliberately does not model a DDR PHY or prove physical calibration.
Use the pinned DDR Python environment and a freshly generated --build-dir.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--generate", action="store_true", help="Regenerate the standalone LiteDRAM core first")
    a = p.parse_args()
    out = a.build_dir.resolve() / "simulation"
    out.mkdir(parents=True, exist_ok=True)
    if a.generate:
        with (out / "generate-driver.log").open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "tools/kc705_ddr_only_build.py"), "generate",
                            "--build-dir", str(a.build_dir)], stdout=log, stderr=subprocess.STDOUT, check=True)
    regs = json.loads((a.build_dir / "litedram/csr.json").read_text())["csr_registers"]
    # Compile the exact generated board engine: full power-up delays, complete
    # PHY search, 2 MiB windows, and production watchdog. No simulation bypass.
    engine = a.build_dir.resolve() / "engine.v"
    (out / "csr_map.h").write_text("\n".join(
        f"constexpr unsigned {name} = {value['addr']//4};" for name, value in regs.items()) + "\n")
    cmd = ["verilator", "--cc", "--exe", "--build", "-j", "2", "-Wno-fatal",
           "--top-module", "kc705_ddr_engine", "--Mdir", str(out / "obj"),
           "-CFLAGS", "-std=c++17 -I" + str(out), str(engine),
           str(ROOT / "tests/kc705_ddr_only_test.cpp")]
    with (out / "compile.log").open("w") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    for mode in ("pass", "reset", "write-level", "write-level-zero", "read-eye", "narrow-eye", "data", "alias", "mask",
                 "csr-timeout", "csr-error", "memory-timeout", "memory-error"):
        result = subprocess.run([str(out / "obj/Vkc705_ddr_engine"), mode],
                                text=True, capture_output=True)
        (out / (mode + ".log")).write_text(result.stdout + result.stderr)
        print(result.stdout + result.stderr, end="", flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
