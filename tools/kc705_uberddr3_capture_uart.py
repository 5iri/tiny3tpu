#!/usr/bin/env python3
"""Load the UART diagnostic image into FPGA SRAM and capture its binary frames."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import serial


def decode(data):
    samples = []
    pos = 0
    while pos + 9 <= len(data):
        if data[pos:pos + 2] != b"\xa5\x5a":
            pos += 1
            continue
        seq, sticky = data[pos + 2:pos + 4]
        debug = int.from_bytes(data[pos + 4:pos + 8], "little")
        status = data[pos + 8]
        if status & 0xe0:
            pos += 1
            continue
        samples.append({
            "sequence": seq, "sticky": sticky, "debug": debug,
            "lane": (debug >> 5) & 7,
            "tap": debug & 31,
            "iserdes_dq0": (debug >> 24) & 1,
            "dqs_toggle_requested": (debug >> 23) & 1,
            "odt": (debug >> 28) & 1,
            "dqs_enable": (debug >> 27) & 1,
            "dqs_input": (debug >> 26) & 1,
            "dq_input": (debug >> 25) & 1,
            "done": status & 1,
            "passed": (status >> 1) & 1,
            "failed": (status >> 2) & 1,
            "locked": (status >> 3) & 1,
            "pre_serdes_dq0": (status >> 4) & 1,
        })
        pos += 9
    return samples


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bit", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--port", default="/dev/cu.usbserial-0001")
    p.add_argument("--observe-seconds", type=float, default=10)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    data = bytearray()
    with serial.Serial(a.port, baudrate=115200, timeout=0.1) as port:
        port.reset_input_buffer()
        with (a.out / "program.log").open("w") as log:
            proc = subprocess.Popen(["openFPGALoader", "-b", "kc705", str(a.bit)],
                                    stdout=log, stderr=subprocess.STDOUT)
            programmed = None
            deadline = None
            while deadline is None or time.monotonic() < deadline:
                data.extend(port.read(8192))
                if programmed is None and proc.poll() is not None:
                    programmed = proc.returncode
                    deadline = time.monotonic() + a.observe_seconds
                    print("JTAG SRAM load exit:", programmed, flush=True)
            if programmed is None:
                programmed = proc.wait()
    (a.out / "uart.bin").write_bytes(data)
    samples = decode(data)
    (a.out / "samples.jsonl").write_text("".join(json.dumps(s) + "\n" for s in samples))
    result = {
        "bitstream": str(a.bit),
        "bitstream_sha256": hashlib.sha256(a.bit.read_bytes()).hexdigest(),
        "program_exit": programmed,
        "capture_bytes": len(data),
        "frames": len(samples),
        "final_sticky": samples[-1]["sticky"] if samples else None,
        "sticky_flags": {
            name: bool(samples and samples[-1]["sticky"] & (1 << bit))
            for bit, name in enumerate(("phy_ready", "odt_requested", "dqs_requested",
                                         "dqs_pad_output", "dq_pad_input", "dq0_low_seen",
                                         "dq0_high_seen", "pre_serdes_dq0_high_seen"))
        },
        "lanes_seen": sorted({s["lane"] for s in samples}),
        "tap_min": min((s["tap"] for s in samples), default=None),
        "tap_max": max((s["tap"] for s in samples), default=None),
        "any_done": any(s["done"] for s in samples),
        "any_passed": any(s["passed"] for s in samples),
        "any_failed": any(s["failed"] for s in samples),
        "dqs_toggle_requested_seen": any(s["dqs_toggle_requested"] for s in samples),
        "first_samples": samples[:3],
        "last_samples": samples[-3:],
    }
    (a.out / "capture.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    if programmed or not samples:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
