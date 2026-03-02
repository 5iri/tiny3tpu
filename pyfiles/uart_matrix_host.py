#!/usr/bin/env python3
"""
Binary host client (UART/UDP) for DDR-backed 16x16 GEMM firmware.

Request frame (little-endian):
  u32 magic=BIN_REQ_MAGIC
  s32 shift
  s8  A[256] row-major
  s8  B[256] row-major

Response frame (little-endian):
  u32 magic=BIN_RESP_MAGIC
  s32 status
  u64 hw_cycles
  u64 counts_per_second
  u32 mmio_retries
  u32 mmio_fails
  s32 C[256] row-major
"""

from __future__ import annotations

import argparse
import random
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import serial  # type: ignore
except Exception as exc:  # pragma: no cover
    serial = None
    SERIAL_IMPORT_ERROR = exc
else:
    SERIAL_IMPORT_ERROR = None


MAT_N = 16
ELEM_COUNT = MAT_N * MAT_N
BIN_REQ_MAGIC = 0x3154414D  # "MAT1"
BIN_RESP_MAGIC = 0x31505352  # "RSP1"

RESP_HEADER_STRUCT = struct.Struct("<iQQII")
RESP_MATRIX_STRUCT = struct.Struct(f"<{ELEM_COUNT}i")


def _load_matrix(path: Path) -> List[List[int]]:
    vals: List[int] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        for tok in line.replace(",", " ").split():
            vals.append(int(tok))
    if len(vals) != ELEM_COUNT:
        raise ValueError(f"{path}: expected {ELEM_COUNT} ints, got {len(vals)}")
    return [vals[r * MAT_N : (r + 1) * MAT_N] for r in range(MAT_N)]


def _gen_matrix(seed: int, lo: int, hi: int) -> List[List[int]]:
    rng = random.Random(seed)
    return [[rng.randint(lo, hi) for _ in range(MAT_N)] for _ in range(MAT_N)]


def _flatten(m: List[List[int]]) -> List[int]:
    out: List[int] = []
    for row in m:
        out.extend(row)
    return out


def _ensure_i8(vals: List[int], name: str) -> None:
    for idx, v in enumerate(vals):
        if v < -128 or v > 127:
            raise ValueError(f"{name}[{idx}]={v} is outside int8 range [-128,127]")


def _matmul_sw(a: List[List[int]], b: List[List[int]]) -> List[List[int]]:
    c = [[0 for _ in range(MAT_N)] for _ in range(MAT_N)]
    for i in range(MAT_N):
        for j in range(MAT_N):
            s = 0
            for k in range(MAT_N):
                s += a[i][k] * b[k][j]
            c[i][j] = s
    return c


def _apply_shift(v: int, shift: int) -> int:
    if shift > 0:
        return v >> shift
    if shift < 0:
        return v << (-shift)
    return v


def _read_exact(ser: "serial.Serial", n: int, timeout_s: float) -> bytes:
    deadline = time.time() + timeout_s
    buf = bytearray()
    while len(buf) < n:
        if time.time() > deadline:
            raise TimeoutError(f"Timed out reading {n} bytes ({len(buf)} received)")
        chunk = ser.read(n - len(buf))
        if chunk:
            buf.extend(chunk)
    return bytes(buf)


def _wait_for_magic(ser: "serial.Serial", magic: int, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    window = 0
    ascii_bytes = bytearray()
    while time.time() < deadline:
        b = ser.read(1)
        if not b:
            continue
        ch = b[0]
        if ch in (9, 10, 13) or (32 <= ch <= 126):
            ascii_bytes.append(ch)
            if len(ascii_bytes) > 256:
                del ascii_bytes[:128]
        window = ((window >> 8) | (ch << 24)) & 0xFFFFFFFF
        if window == magic:
            return
    hint = ""
    text = ascii_bytes.decode("ascii", errors="ignore")
    if ("HOST_MODE_READY" in text) or ("Systolic" in text) or ("HOST_RESULT_BEGIN" in text):
        hint = " (ASCII firmware output detected; flash binary-protocol firmware)"
    raise TimeoutError(f"Timed out waiting for response magic 0x{magic:08x}{hint}")


def _read_response(ser: "serial.Serial", timeout_s: float) -> Tuple[int, Dict[str, int], List[List[int]]]:
    _wait_for_magic(ser, BIN_RESP_MAGIC, timeout_s)
    hdr = _read_exact(ser, RESP_HEADER_STRUCT.size, timeout_s)
    status, hw_cycles, cps, retries, fails = RESP_HEADER_STRUCT.unpack(hdr)
    mat_raw = _read_exact(ser, RESP_MATRIX_STRUCT.size, timeout_s)
    c_vals = RESP_MATRIX_STRUCT.unpack(mat_raw)
    c_hw = [list(c_vals[r * MAT_N : (r + 1) * MAT_N]) for r in range(MAT_N)]
    stats = {
        "HOST_HW_CYCLES": int(hw_cycles),
        "COUNTS_PER_SECOND": int(cps),
        "MMIO_RETRIES": int(retries),
        "MMIO_FAILS": int(fails),
    }
    return int(status), stats, c_hw


def _read_response_udp(resp: bytes) -> Tuple[int, Dict[str, int], List[List[int]]]:
    magic = struct.pack("<I", BIN_RESP_MAGIC)
    idx = resp.find(magic)
    if idx < 0:
        raise RuntimeError(f"response missing magic 0x{BIN_RESP_MAGIC:08x}, got {len(resp)} bytes")
    resp = resp[idx:]
    if len(resp) < 4 + RESP_HEADER_STRUCT.size + RESP_MATRIX_STRUCT.size:
        raise RuntimeError(f"short UDP response: {len(resp)} bytes")
    status, hw_cycles, cps, retries, fails = RESP_HEADER_STRUCT.unpack_from(resp, 4)
    c_vals = RESP_MATRIX_STRUCT.unpack_from(resp, 4 + RESP_HEADER_STRUCT.size)
    c_hw = [list(c_vals[r * MAT_N : (r + 1) * MAT_N]) for r in range(MAT_N)]
    stats = {
        "HOST_HW_CYCLES": int(hw_cycles),
        "COUNTS_PER_SECOND": int(cps),
        "MMIO_RETRIES": int(retries),
        "MMIO_FAILS": int(fails),
    }
    return int(status), stats, c_hw


def run_once(
    ser: "serial.Serial",
    a: List[List[int]],
    b: List[List[int]],
    shift: int,
    timeout_s: float,
) -> None:
    flat_a = _flatten(a)
    flat_b = _flatten(b)
    _ensure_i8(flat_a, "A")
    _ensure_i8(flat_b, "B")
    payload = struct.pack("<Ii", BIN_REQ_MAGIC, int(shift))
    payload += struct.pack(f"<{ELEM_COUNT}b", *flat_a)
    payload += struct.pack(f"<{ELEM_COUNT}b", *flat_b)

    t0 = time.time()
    ser.write(payload)
    ser.flush()

    status, stats, c_hw = _read_response(ser, timeout_s)
    t1 = time.time()

    if status != 0:
        raise RuntimeError(f"hardware status={status}")

    c_sw = _matmul_sw(a, b)
    mismatches = 0
    for i in range(MAT_N):
        for j in range(MAT_N):
            sw = _apply_shift(c_sw[i][j], shift)
            if int(c_hw[i][j]) != sw:
                mismatches += 1

    print(
        f"HOST_HW_CYCLES {stats['HOST_HW_CYCLES']} "
        f"COUNTS_PER_SECOND {stats['COUNTS_PER_SECOND']} "
        f"MMIO_RETRIES {stats['MMIO_RETRIES']} "
        f"MMIO_FAILS {stats['MMIO_FAILS']}"
    )
    print(f"HOST_ROUNDTRIP_MS {(t1 - t0) * 1000.0:.3f}")
    if mismatches == 0:
        print("CHECK PASS")
    else:
        print(f"CHECK FAIL mismatches={mismatches}")


def run_once_udp(
    sock: socket.socket,
    dst: Tuple[str, int],
    a: List[List[int]],
    b: List[List[int]],
    shift: int,
    timeout_s: float,
    udp_retries: int,
) -> None:
    flat_a = _flatten(a)
    flat_b = _flatten(b)
    _ensure_i8(flat_a, "A")
    _ensure_i8(flat_b, "B")
    payload = struct.pack("<Ii", BIN_REQ_MAGIC, int(shift))
    payload += struct.pack(f"<{ELEM_COUNT}b", *flat_a)
    payload += struct.pack(f"<{ELEM_COUNT}b", *flat_b)

    t0 = time.time()
    last_exc: Exception | None = None
    attempts = max(1, int(udp_retries) + 1)
    resp = b""
    for _ in range(attempts):
        sock.send(payload)
        sock.settimeout(timeout_s)
        try:
            resp = sock.recv(131072)
            break
        except socket.timeout as exc:
            last_exc = exc
    if not resp:
        src_ip, src_port = sock.getsockname()
        raise TimeoutError(
            f"Timed out waiting for UDP response after {attempts} attempt(s) "
            f"dst={dst[0]}:{dst[1]} src={src_ip}:{src_port}. "
            "Check that host and FPGA are in the same IPv4 subnet and firmware UDP mode is running."
        ) from last_exc
    status, stats, c_hw = _read_response_udp(resp)
    t1 = time.time()

    if status != 0:
        raise RuntimeError(f"hardware status={status}")

    c_sw = _matmul_sw(a, b)
    mismatches = 0
    for i in range(MAT_N):
        for j in range(MAT_N):
            sw = _apply_shift(c_sw[i][j], shift)
            if int(c_hw[i][j]) != sw:
                mismatches += 1

    print(
        f"HOST_HW_CYCLES {stats['HOST_HW_CYCLES']} "
        f"COUNTS_PER_SECOND {stats['COUNTS_PER_SECOND']} "
        f"MMIO_RETRIES {stats['MMIO_RETRIES']} "
        f"MMIO_FAILS {stats['MMIO_FAILS']}"
    )
    print(f"HOST_ROUNDTRIP_MS {(t1 - t0) * 1000.0:.3f}")
    if mismatches == 0:
        print("CHECK PASS")
    else:
        print(f"CHECK FAIL mismatches={mismatches}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="UART port, e.g. /dev/ttyUSB1")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--udp-host", type=str, help="FPGA IPv4 for UDP mode")
    ap.add_argument("--udp-port", type=int, default=9001)
    ap.add_argument("--udp-local-ip", type=str, default="0.0.0.0", help="local source IPv4 to bind")
    ap.add_argument("--udp-local-port", type=int, default=0)
    ap.add_argument("--udp-retries", type=int, default=2, help="UDP retries on timeout (default: 2)")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--shift", type=int, default=0, help="Arithmetic shift applied by firmware")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--seed", type=int, default=123)
    ap.add_argument("--lo", type=int, default=-8)
    ap.add_argument("--hi", type=int, default=8)
    ap.add_argument("--a-file", type=Path, default=None, help=f"Matrix A file ({ELEM_COUNT} ints)")
    ap.add_argument("--b-file", type=Path, default=None, help=f"Matrix B file ({ELEM_COUNT} ints)")
    args = ap.parse_args()

    if (args.udp_host is None) and (serial is None):
        print(f"pyserial import failed: {SERIAL_IMPORT_ERROR}", file=sys.stderr)
        return 2

    if args.a_file:
        a = _load_matrix(args.a_file)
    else:
        a = _gen_matrix(args.seed, args.lo, args.hi)

    if args.b_file:
        b = _load_matrix(args.b_file)
    else:
        b = _gen_matrix(args.seed + 1, args.lo, args.hi)

    if args.udp_host:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            bind_ip = str(args.udp_local_ip or "0.0.0.0")
            bind_port = int(args.udp_local_port)
            if (bind_ip != "0.0.0.0") or (bind_port > 0):
                sock.bind((bind_ip, bind_port))
            dst = (str(args.udp_host), int(args.udp_port))
            sock.connect(dst)
            src_ip, src_port = sock.getsockname()
            print(f"transport=udp {args.udp_host}:{args.udp_port} src={src_ip}:{src_port}")
            for idx in range(args.repeat):
                print(f"RUN {idx + 1}/{args.repeat}")
                run_once_udp(sock, dst, a, b, args.shift, args.timeout, args.udp_retries)
    else:
        if not args.port:
            raise ValueError("UART mode requires --port (or use --udp-host)")
        with serial.Serial(args.port, args.baud, timeout=0.05) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            print(f"transport=uart {args.port} @ {args.baud}")
            for idx in range(args.repeat):
                print(f"RUN {idx + 1}/{args.repeat}")
                run_once(ser, a, b, args.shift, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
