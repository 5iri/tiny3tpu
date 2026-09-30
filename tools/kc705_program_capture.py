#!/usr/bin/env python3
"""Load a checked image into KC705 SRAM and retain its UART bring-up evidence.

Requires pyserial. No SPI/BPI flash is written. Open UART before configuration
so that the initial calibration output is captured as well as the final result.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import serial


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--uart", default="/dev/cu.usbserial-0001")
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument("--success", default="PASS: DDR-backed signed TPU GEMM")
    p.add_argument("--failure", default="FAIL: DDR/TPU bring-up")
    p.add_argument("--label", default="hardware")
    a = p.parse_args()
    if not a.label or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in a.label):
        p.error("label must be a simple filename prefix")
    build = a.build_dir.resolve()
    bit = build / "soc.bit"
    manifest = json.loads((build / "bitstream-manifest.json").read_text())
    if not manifest["passed"]:
        p.error("bitstream manifest did not pass")
    # The export records absolute file paths. Check all artifacts, not just the
    # bitstream, so a later firmware/constraint edit cannot inherit old evidence.
    for path, digest in manifest["sha256"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            p.error("artifact changed since export: " + path)
    digest = hashlib.sha256(bit.read_bytes()).hexdigest()
    if manifest["sha256"].get(str(bit)) != digest:
        p.error("bitstream is not bound to the export manifest")
    data = bytearray()
    program_log = build / (a.label + "-program.log")
    started = time.monotonic()
    with serial.Serial(a.uart, 115200, timeout=.2, rtscts=False, dsrdtr=False) as uart:
        uart.reset_input_buffer()
        with program_log.open("w") as log:
            rc = subprocess.run(["openFPGALoader", "-b", "kc705", str(bit)],
                                stdout=log, stderr=subprocess.STDOUT).returncode
        print(program_log.read_text(), flush=True)
        deadline = time.monotonic() + a.timeout
        while rc == 0 and time.monotonic() < deadline:
            chunk = uart.read(4096)
            data.extend(chunk)
            if chunk:
                print(chunk.decode("ascii", errors="backslashreplace"), end="", flush=True)
            if a.success.encode() in data or a.failure.encode() in data:
                # Drain the trailing newline and any final status before closing.
                data.extend(uart.read(4096))
                break
    (build / (a.label + "-uart.bin")).write_bytes(data)
    (build / (a.label + "-uart.log")).write_text(data.decode("ascii", errors="backslashreplace"))
    passed = rc == 0 and a.success.encode() in data and a.failure.encode() not in data
    record = dict(passed=passed, program_exit=rc,
                  programming="volatile FPGA configuration RAM",
                  bitstream_sha256=digest, io_profile=manifest.get("io_profile"),
                  clocks=manifest["clocks"], success_marker=a.success,
                  elapsed_seconds=round(time.monotonic()-started, 2))
    (build / (a.label + "-result.json")).write_text(json.dumps(record, indent=2) + "\n")
    print("\n" + json.dumps(record, indent=2), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
