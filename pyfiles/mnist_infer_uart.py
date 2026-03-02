#!/usr/bin/env python3
"""
MNIST inference demo over the 16x16 systolic-array binary packet protocol.

Firmware protocol (binary little-endian):
Request:
  GEMM:  u32 magic=BIN_REQ_MAGIC, s32 shift, s8 A[256], s8 B[256]
  LOAD:  u32 magic=BIN_REQ_MODEL_MAGIC, u32 proto_version=2, u32 layer_count,
         u32 dims[layer_count+1], then for each layer:
         s32 rq_mult, u32 rq_shift, u32 flags,
         s8 W[out_dim][in_dim], s32 B[out_dim]
         flags bit0=requant, bit1=relu
  INFER: u32 magic=BIN_REQ_INFER_MAGIC, s8 X[in_dim]
Response:
  GEMM:  u32 magic=BIN_RESP_MAGIC, s32 status, u64 cycles, u64 counts_per_second,
         u32 mmio_retries, u32 mmio_fails, s32 C[256]
  ACK:   u32 magic=BIN_RESP_ACK_MAGIC, s32 status
  INFER: u32 magic=BIN_RESP_INFER_MAGIC, s32 status, u64 cycles, u64 counts_per_second,
         u32 hw_packets, s32 pred, u32 logits_count, s32 logits[logits_count]

This script:
1) Loads quantized MNIST model JSON (default: mnist_int8.json)
2) Loads MNIST test images/labels from IDX files
3) Runs quantized MLP inference where each linear layer is mapped to tiled
   16x16 GEMMs over UART/UDP or via cached-model INF path.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import serial  # type: ignore
except Exception as exc:  # pragma: no cover
    serial = None
    SERIAL_IMPORT_ERROR = exc
else:
    SERIAL_IMPORT_ERROR = None


TILE = 16
ELEM_COUNT = TILE * TILE
BIN_REQ_MAGIC = 0x3154414D  # "MAT1"
BIN_RESP_MAGIC = 0x31505352  # "RSP1"
BIN_REQ_MODEL_MAGIC = 0x31444F4D  # "MOD1"
BIN_REQ_MODEL_CHUNK_MAGIC = 0x3148434D  # "MCH1"
BIN_REQ_INFER_MAGIC = 0x31464E49  # "INF1"
BIN_RESP_ACK_MAGIC = 0x314B4341  # "ACK1"
BIN_RESP_INFER_MAGIC = 0x31445250  # "PRD1"
MODEL_PROTO_VERSION = 0x00020000
MODEL_FLAG_REQUANT = 1 << 0
MODEL_FLAG_RELU = 1 << 1
MODEL_CHUNK_FLAG_START = 1 << 0
MODEL_CHUNK_FLAG_END = 1 << 1
FW_MAX_MODEL_DIM = 256
FW_MAX_MODEL_LAYERS = 16
UDP_MAX_DGRAM_PAYLOAD = 65507
UDP_MODEL_CHUNK_DATA_BYTES = 1200

RESP_HEADER_STRUCT = struct.Struct("<iQQII")
RESP_MATRIX_STRUCT = struct.Struct(f"<{ELEM_COUNT}i")
RESP_ACK_STRUCT = struct.Struct("<i")
RESP_INFER_HDR_STRUCT = struct.Struct("<iQQIiI")


def clamp_i8(v: int) -> int:
    if v < -128:
        return -128
    if v > 127:
        return 127
    return v


def require_i8(v: int, name: str) -> int:
    if v < -128 or v > 127:
        raise ValueError(f"{name}={v} is outside int8 range [-128,127]")
    return int(v)


def choose_requant_params(multiplier: float, shift: int = 24) -> Tuple[int, int]:
    if multiplier < 0:
        raise ValueError(f"requant multiplier must be >=0, got {multiplier}")
    m = int(round(multiplier * float(1 << shift)))
    if m > 0x7FFFFFFF:
        m = 0x7FFFFFFF
    return m, shift


def argmax(vals: Sequence[float]) -> int:
    best_i = 0
    best_v = vals[0]
    for i in range(1, len(vals)):
        if vals[i] > best_v:
            best_v = vals[i]
            best_i = i
    return best_i


def read_idx_images(path: Path) -> Tuple[bytes, int, int, int]:
    raw = path.read_bytes()
    if len(raw) < 16:
        raise ValueError(f"{path}: too short for IDX image header")
    magic, count, rows, cols = struct.unpack_from(">IIII", raw, 0)
    if magic != 2051:
        raise ValueError(f"{path}: bad image magic {magic}, expected 2051")
    need = count * rows * cols
    data = raw[16:]
    if len(data) < need:
        raise ValueError(f"{path}: image payload too short ({len(data)} < {need})")
    return data[:need], count, rows, cols


def read_idx_labels(path: Path) -> Tuple[bytes, int]:
    raw = path.read_bytes()
    if len(raw) < 8:
        raise ValueError(f"{path}: too short for IDX label header")
    magic, count = struct.unpack_from(">II", raw, 0)
    if magic != 2049:
        raise ValueError(f"{path}: bad label magic {magic}, expected 2049")
    data = raw[8:]
    if len(data) < count:
        raise ValueError(f"{path}: label payload too short ({len(data)} < {count})")
    return data[:count], count


def resize_gray_nn(src: Sequence[int], src_h: int, src_w: int, dst_h: int, dst_w: int) -> List[int]:
    out = [0] * (dst_h * dst_w)
    for y in range(dst_h):
        sy = min((y * src_h) // dst_h, src_h - 1)
        for x in range(dst_w):
            sx = min((x * src_w) // dst_w, src_w - 1)
            out[y * dst_w + x] = int(src[sy * src_w + sx])
    return out


class UartSystolicClient:
    def __init__(self, port: str, baud: int, timeout_s: float) -> None:
        if serial is None:
            raise RuntimeError(f"pyserial import failed: {SERIAL_IMPORT_ERROR}")
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.timeout_s = timeout_s
        self.packet_count = 0
        self.hw_cycles = 0
        self.mmio_retries = 0
        self.mmio_fails = 0
        self.counts_per_second: Optional[int] = None
        self.cached_model_loaded = False
        self.cached_input_dim = 0
        self.cached_output_dim = 0
        self.cached_layer_count = 0

    def close(self) -> None:
        self.ser.close()

    def reset_stats(self) -> None:
        self.packet_count = 0
        self.hw_cycles = 0
        self.mmio_retries = 0
        self.mmio_fails = 0

    def _read_exact(self, n: int) -> bytes:
        deadline = time.time() + self.timeout_s
        buf = bytearray()
        while len(buf) < n:
            if time.time() > deadline:
                raise TimeoutError(f"Timeout reading {n} bytes ({len(buf)} received)")
            chunk = self.ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
        return bytes(buf)

    def _wait_for_magic(self, magic: int) -> None:
        deadline = time.time() + self.timeout_s
        window = 0
        ascii_bytes = bytearray()
        while time.time() < deadline:
            b = self.ser.read(1)
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
        raise TimeoutError(f"Timeout waiting for magic 0x{magic:08x}{hint}")

    def load_model_cached(self, model: Dict[str, object]) -> None:
        layers = model["layers"]  # type: ignore[index]
        if not isinstance(layers, list) or len(layers) < 1:
            raise ValueError("model requires at least one linear layer")
        if len(layers) > FW_MAX_MODEL_LAYERS:
            raise ValueError(
                f"model has {len(layers)} layers; firmware cache limit is {FW_MAX_MODEL_LAYERS}"
            )

        dims: List[int] = []
        packed_layers: List[Tuple[int, int, int, List[int], List[int]]] = []
        for li, layer in enumerate(layers):
            w = layer["w"]
            b = layer["b"]
            out_dim = len(w)
            in_dim = len(w[0]) if out_dim else 0
            if out_dim <= 0 or in_dim <= 0:
                raise ValueError(f"layer{li}: invalid shape")
            if out_dim > FW_MAX_MODEL_DIM or in_dim > FW_MAX_MODEL_DIM:
                raise ValueError(f"layer{li}: dims too large for firmware cache ({out_dim}x{in_dim})")
            if li == 0:
                dims.append(in_dim)
            elif dims[-1] != in_dim:
                raise ValueError(f"layer{li}: input dim {in_dim} != previous output dim {dims[-1]}")
            dims.append(out_dim)
            if len(b) != out_dim:
                raise ValueError(f"layer{li}: bias length mismatch ({len(b)} != {out_dim})")

            flat_w: List[int] = []
            for o in range(out_dim):
                row = w[o]
                if len(row) != in_dim:
                    raise ValueError(f"layer{li}: weight rows have inconsistent lengths")
                for i in range(in_dim):
                    flat_w.append(require_i8(int(row[i]), f"W[{li}][{o}][{i}]"))
            flat_b = [int(x) for x in b]

            is_last = li == (len(layers) - 1)
            if is_last and bool(layer.get("output_requant", False)):
                rq = (float(layer["scale_in"]) * float(layer["scale_w"])) / max(float(layer["scale_out"]), 1e-12)
                rq_mult, rq_shift = choose_requant_params(rq, shift=24)
                activation = str(layer.get("activation", "none")).lower()
                if activation not in ("relu", "none", "linear", "identity"):
                    raise ValueError(f"layer{li}: unsupported activation '{activation}'")
                flags = MODEL_FLAG_REQUANT
                if activation == "relu":
                    flags |= MODEL_FLAG_RELU
            elif is_last:
                rq_mult, rq_shift, flags = 0, 0, 0
            else:
                rq = (float(layer["scale_in"]) * float(layer["scale_w"])) / max(float(layer["scale_out"]), 1e-12)
                rq_mult, rq_shift = choose_requant_params(rq, shift=24)
                activation = str(layer.get("activation", "relu")).lower()
                if activation not in ("relu", "none", "linear", "identity"):
                    raise ValueError(f"layer{li}: unsupported activation '{activation}'")
                flags = MODEL_FLAG_REQUANT
                if activation == "relu":
                    flags |= MODEL_FLAG_RELU

            packed_layers.append((rq_mult, rq_shift, flags, flat_w, flat_b))

        payload = bytearray()
        payload += struct.pack("<I", BIN_REQ_MODEL_MAGIC)
        payload += struct.pack("<II", MODEL_PROTO_VERSION, len(layers))
        payload += struct.pack(f"<{len(dims)}I", *[int(x) for x in dims])
        for rq_mult, rq_shift, flags, flat_w, flat_b in packed_layers:
            payload += struct.pack("<iII", int(rq_mult), int(rq_shift), int(flags))
            payload += struct.pack(f"<{len(flat_w)}b", *flat_w)
            payload += struct.pack(f"<{len(flat_b)}i", *flat_b)

        self.ser.write(bytes(payload))
        self.ser.flush()

        self._wait_for_magic(BIN_RESP_ACK_MAGIC)
        ack = self._read_exact(RESP_ACK_STRUCT.size)
        (status,) = RESP_ACK_STRUCT.unpack(ack)
        if status != 0:
            raise RuntimeError(f"model load failed status={status}")

        self.cached_model_loaded = True
        self.cached_input_dim = int(dims[0])
        self.cached_output_dim = int(dims[-1])
        self.cached_layer_count = len(layers)

    def infer_cached(self, x_q: Sequence[int]) -> Tuple[int, List[int], int]:
        if not self.cached_model_loaded:
            raise RuntimeError("cached model is not loaded")
        if len(x_q) != self.cached_input_dim:
            raise ValueError(f"input length {len(x_q)} != cached input_dim {self.cached_input_dim}")
        flat_x = [require_i8(int(v), f"x[{i}]") for i, v in enumerate(x_q)]

        payload = struct.pack("<I", BIN_REQ_INFER_MAGIC)
        payload += struct.pack(f"<{len(flat_x)}b", *flat_x)
        self.ser.write(payload)
        self.ser.flush()

        self._wait_for_magic(BIN_RESP_INFER_MAGIC)
        hdr = self._read_exact(RESP_INFER_HDR_STRUCT.size)
        status, hw_cycles, cps, hw_packets, pred, logits_count = RESP_INFER_HDR_STRUCT.unpack(hdr)
        if logits_count > FW_MAX_MODEL_DIM:
            raise RuntimeError(f"firmware returned invalid logits_count={logits_count}")
        logits = []
        if logits_count > 0:
            logits_raw = self._read_exact(int(logits_count) * 4)
            logits = list(struct.unpack(f"<{logits_count}i", logits_raw))
        if status != 0:
            raise RuntimeError(f"infer failed status={status}")
        if self.cached_output_dim and logits_count != self.cached_output_dim:
            raise RuntimeError(
                f"infer logits_count mismatch: firmware={logits_count} expected={self.cached_output_dim}"
            )

        self.packet_count += int(hw_packets)
        self.hw_cycles += int(hw_cycles)
        self.counts_per_second = int(cps)
        return int(pred), logits, int(hw_packets)

    def run_packet(self, a16: Sequence[Sequence[int]], b16: Sequence[Sequence[int]], shift: int = 0) -> List[List[int]]:
        flat_a: List[int] = []
        flat_b: List[int] = []
        for r in range(TILE):
            for c in range(TILE):
                flat_a.append(require_i8(int(a16[r][c]), f"A[{r}][{c}]"))
        for r in range(TILE):
            for c in range(TILE):
                flat_b.append(require_i8(int(b16[r][c]), f"B[{r}][{c}]"))

        payload = struct.pack("<Ii", BIN_REQ_MAGIC, int(shift))
        payload += struct.pack(f"<{ELEM_COUNT}b", *flat_a)
        payload += struct.pack(f"<{ELEM_COUNT}b", *flat_b)
        self.ser.write(payload)
        self.ser.flush()

        self._wait_for_magic(BIN_RESP_MAGIC)
        hdr = self._read_exact(RESP_HEADER_STRUCT.size)
        status, hw_cycles, cps, mmio_retries, mmio_fails = RESP_HEADER_STRUCT.unpack(hdr)
        mat_raw = self._read_exact(RESP_MATRIX_STRUCT.size)
        c_vals = RESP_MATRIX_STRUCT.unpack(mat_raw)
        c16 = [list(c_vals[r * TILE : (r + 1) * TILE]) for r in range(TILE)]

        if status != 0:
            raise RuntimeError(f"hardware status={status}")

        self.packet_count += 1
        self.hw_cycles += int(hw_cycles)
        self.mmio_retries += int(mmio_retries)
        self.mmio_fails += int(mmio_fails)
        self.counts_per_second = int(cps)

        return c16

    def matmul_tiled(self, a: Sequence[Sequence[int]], b: Sequence[Sequence[int]]) -> List[List[int]]:
        m = len(a)
        if m == 0:
            return []
        k = len(a[0])
        if k == 0:
            return [[0] * len(b[0]) for _ in range(m)]
        if len(b) != k:
            raise ValueError(f"matmul dim mismatch: A is {m}x{k}, B is {len(b)}x{len(b[0]) if b else 0}")
        n = len(b[0])

        c = [[0 for _ in range(n)] for _ in range(m)]

        for i0 in range(0, m, TILE):
            im = min(TILE, m - i0)
            for j0 in range(0, n, TILE):
                jn = min(TILE, n - j0)
                block = [[0 for _ in range(jn)] for _ in range(im)]

                for k0 in range(0, k, TILE):
                    kk = min(TILE, k - k0)

                    a16 = [[0 for _ in range(TILE)] for _ in range(TILE)]
                    b16 = [[0 for _ in range(TILE)] for _ in range(TILE)]

                    for i in range(im):
                        for t in range(kk):
                            a16[i][t] = int(a[i0 + i][k0 + t])
                    for t in range(kk):
                        for j in range(jn):
                            b16[t][j] = int(b[k0 + t][j0 + j])

                    c16 = self.run_packet(a16, b16, shift=0)
                    for i in range(im):
                        for j in range(jn):
                            block[i][j] += c16[i][j]

                for i in range(im):
                    for j in range(jn):
                        c[i0 + i][j0 + j] = block[i][j]

        return c


class UdpSystolicClient(UartSystolicClient):
    def __init__(
        self,
        host: str,
        port: int,
        timeout_s: float,
        local_port: int = 0,
        local_ip: str = "0.0.0.0",
        retries: int = 2,
    ) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout_s)
        self.udp_retries = max(0, int(retries))
        bind_ip = str(local_ip or "0.0.0.0")
        bind_port = int(local_port)
        if (bind_ip != "0.0.0.0") or (bind_port > 0):
            self.sock.bind((bind_ip, bind_port))
        self.sock.connect((host, int(port)))
        src_ip, src_port = self.sock.getsockname()
        self.src_endpoint = f"{src_ip}:{src_port}"
        self.timeout_s = timeout_s
        self.packet_count = 0
        self.hw_cycles = 0
        self.mmio_retries = 0
        self.mmio_fails = 0
        self.counts_per_second: Optional[int] = None
        self.cached_model_loaded = False
        self.cached_input_dim = 0
        self.cached_output_dim = 0
        self.cached_layer_count = 0

    def close(self) -> None:
        self.sock.close()

    def _xfer(self, payload: bytes) -> bytes:
        last_exc: Exception | None = None
        attempts = self.udp_retries + 1
        for _ in range(attempts):
            self.sock.send(payload)
            try:
                return self.sock.recv(131072)
            except socket.timeout as exc:
                last_exc = exc
        raise TimeoutError(
            "Timeout waiting for UDP response "
            f"after {attempts} attempt(s) src={self.src_endpoint} "
            "(FPGA firmware likely not in UDP mode, wrong IP/port, link not up, or host routed via wrong NIC)"
        ) from last_exc

    @staticmethod
    def _find_magic(resp: bytes, magic: int) -> bytes:
        pat = struct.pack("<I", int(magic))
        idx = resp.find(pat)
        if idx < 0:
            raise RuntimeError(f"response missing magic 0x{magic:08x}, got {len(resp)} bytes")
        return resp[idx:]

    def _request_ack_status(self, payload: bytes) -> int:
        resp = self._find_magic(self._xfer(payload), BIN_RESP_ACK_MAGIC)
        if len(resp) < 4 + RESP_ACK_STRUCT.size:
            raise RuntimeError(f"short ACK response: {len(resp)} bytes")
        (status,) = RESP_ACK_STRUCT.unpack_from(resp, 4)
        return int(status)

    def _load_model_cached_chunked(self, payload: bytes) -> None:
        total_len = len(payload)
        if total_len <= 0:
            raise ValueError("empty model payload")

        offset = 0
        while offset < total_len:
            take = min(UDP_MODEL_CHUNK_DATA_BYTES, total_len - offset)
            flags = 0
            if offset == 0:
                flags |= MODEL_CHUNK_FLAG_START
            if (offset + take) >= total_len:
                flags |= MODEL_CHUNK_FLAG_END

            chunk = payload[offset : offset + take]
            req = struct.pack(
                "<IIIII",
                BIN_REQ_MODEL_CHUNK_MAGIC,
                int(total_len),
                int(offset),
                int(take),
                int(flags),
            )
            req += chunk

            status = self._request_ack_status(req)
            if status != 0:
                raise RuntimeError(
                    f"model chunk upload failed status={status} "
                    f"offset={offset} chunk={take}/{total_len}"
                )
            offset += take

    def load_model_cached(self, model: Dict[str, object]) -> None:
        layers = model["layers"]  # type: ignore[index]
        if not isinstance(layers, list) or len(layers) < 1:
            raise ValueError("model requires at least one linear layer")
        if len(layers) > FW_MAX_MODEL_LAYERS:
            raise ValueError(
                f"model has {len(layers)} layers; firmware cache limit is {FW_MAX_MODEL_LAYERS}"
            )

        dims: List[int] = []
        packed_layers: List[Tuple[int, int, int, List[int], List[int]]] = []
        for li, layer in enumerate(layers):
            w = layer["w"]
            b = layer["b"]
            out_dim = len(w)
            in_dim = len(w[0]) if out_dim else 0
            if out_dim <= 0 or in_dim <= 0:
                raise ValueError(f"layer{li}: invalid shape")
            if out_dim > FW_MAX_MODEL_DIM or in_dim > FW_MAX_MODEL_DIM:
                raise ValueError(f"layer{li}: dims too large for firmware cache ({out_dim}x{in_dim})")
            if li == 0:
                dims.append(in_dim)
            elif dims[-1] != in_dim:
                raise ValueError(f"layer{li}: input dim {in_dim} != previous output dim {dims[-1]}")
            dims.append(out_dim)
            if len(b) != out_dim:
                raise ValueError(f"layer{li}: bias length mismatch ({len(b)} != {out_dim})")

            flat_w: List[int] = []
            for o in range(out_dim):
                row = w[o]
                if len(row) != in_dim:
                    raise ValueError(f"layer{li}: weight rows have inconsistent lengths")
                for i in range(in_dim):
                    flat_w.append(require_i8(int(row[i]), f"W[{li}][{o}][{i}]"))
            flat_b = [int(x) for x in b]

            is_last = li == (len(layers) - 1)
            if is_last and bool(layer.get("output_requant", False)):
                rq = (float(layer["scale_in"]) * float(layer["scale_w"])) / max(float(layer["scale_out"]), 1e-12)
                rq_mult, rq_shift = choose_requant_params(rq, shift=24)
                activation = str(layer.get("activation", "none")).lower()
                if activation not in ("relu", "none", "linear", "identity"):
                    raise ValueError(f"layer{li}: unsupported activation '{activation}'")
                flags = MODEL_FLAG_REQUANT
                if activation == "relu":
                    flags |= MODEL_FLAG_RELU
            elif is_last:
                rq_mult, rq_shift, flags = 0, 0, 0
            else:
                rq = (float(layer["scale_in"]) * float(layer["scale_w"])) / max(float(layer["scale_out"]), 1e-12)
                rq_mult, rq_shift = choose_requant_params(rq, shift=24)
                activation = str(layer.get("activation", "relu")).lower()
                if activation not in ("relu", "none", "linear", "identity"):
                    raise ValueError(f"layer{li}: unsupported activation '{activation}'")
                flags = MODEL_FLAG_REQUANT
                if activation == "relu":
                    flags |= MODEL_FLAG_RELU

            packed_layers.append((rq_mult, rq_shift, flags, flat_w, flat_b))

        payload = bytearray()
        payload += struct.pack("<I", BIN_REQ_MODEL_MAGIC)
        payload += struct.pack("<II", MODEL_PROTO_VERSION, len(layers))
        payload += struct.pack(f"<{len(dims)}I", *[int(x) for x in dims])
        for rq_mult, rq_shift, flags, flat_w, flat_b in packed_layers:
            payload += struct.pack("<iII", int(rq_mult), int(rq_shift), int(flags))
            payload += struct.pack(f"<{len(flat_w)}b", *flat_w)
            payload += struct.pack(f"<{len(flat_b)}i", *flat_b)

        payload_bytes = bytes(payload)
        if len(payload_bytes) > UDP_MAX_DGRAM_PAYLOAD:
            self._load_model_cached_chunked(payload_bytes)
        else:
            status = self._request_ack_status(payload_bytes)
            if status != 0:
                raise RuntimeError(f"model load failed status={status}")

        self.cached_model_loaded = True
        self.cached_input_dim = int(dims[0])
        self.cached_output_dim = int(dims[-1])
        self.cached_layer_count = len(layers)

    def infer_cached(self, x_q: Sequence[int]) -> Tuple[int, List[int], int]:
        if not self.cached_model_loaded:
            raise RuntimeError("cached model is not loaded")
        if len(x_q) != self.cached_input_dim:
            raise ValueError(f"input length {len(x_q)} != cached input_dim {self.cached_input_dim}")

        flat_x = [require_i8(int(v), f"x[{i}]") for i, v in enumerate(x_q)]
        payload = struct.pack("<I", BIN_REQ_INFER_MAGIC)
        payload += struct.pack(f"<{len(flat_x)}b", *flat_x)

        resp = self._find_magic(self._xfer(payload), BIN_RESP_INFER_MAGIC)
        if len(resp) < 4 + RESP_INFER_HDR_STRUCT.size:
            raise RuntimeError(f"short infer header: {len(resp)} bytes")
        status, hw_cycles, cps, hw_packets, pred, logits_count = RESP_INFER_HDR_STRUCT.unpack_from(resp, 4)
        if logits_count > FW_MAX_MODEL_DIM:
            raise RuntimeError(f"firmware returned invalid logits_count={logits_count}")
        need = 4 + RESP_INFER_HDR_STRUCT.size + int(logits_count) * 4
        if len(resp) < need:
            raise RuntimeError(f"short infer payload: expected {need} got {len(resp)}")
        logits: List[int] = []
        if logits_count > 0:
            logits = list(struct.unpack_from(f"<{logits_count}i", resp, 4 + RESP_INFER_HDR_STRUCT.size))
        if status != 0:
            raise RuntimeError(f"infer failed status={status}")
        if self.cached_output_dim and logits_count != self.cached_output_dim:
            raise RuntimeError(
                f"infer logits_count mismatch: firmware={logits_count} expected={self.cached_output_dim}"
            )

        self.packet_count += int(hw_packets)
        self.hw_cycles += int(hw_cycles)
        self.counts_per_second = int(cps)
        return int(pred), logits, int(hw_packets)

    def run_packet(self, a16: Sequence[Sequence[int]], b16: Sequence[Sequence[int]], shift: int = 0) -> List[List[int]]:
        flat_a: List[int] = []
        flat_b: List[int] = []
        for r in range(TILE):
            for c in range(TILE):
                flat_a.append(require_i8(int(a16[r][c]), f"A[{r}][{c}]"))
        for r in range(TILE):
            for c in range(TILE):
                flat_b.append(require_i8(int(b16[r][c]), f"B[{r}][{c}]"))

        payload = struct.pack("<Ii", BIN_REQ_MAGIC, int(shift))
        payload += struct.pack(f"<{ELEM_COUNT}b", *flat_a)
        payload += struct.pack(f"<{ELEM_COUNT}b", *flat_b)

        resp = self._find_magic(self._xfer(payload), BIN_RESP_MAGIC)
        if len(resp) < 4 + RESP_HEADER_STRUCT.size + RESP_MATRIX_STRUCT.size:
            raise RuntimeError(f"short GEMM response: {len(resp)} bytes")
        status, hw_cycles, cps, mmio_retries, mmio_fails = RESP_HEADER_STRUCT.unpack_from(resp, 4)
        c_vals = RESP_MATRIX_STRUCT.unpack_from(resp, 4 + RESP_HEADER_STRUCT.size)
        c16 = [list(c_vals[r * TILE : (r + 1) * TILE]) for r in range(TILE)]

        if status != 0:
            raise RuntimeError(f"hardware status={status}")

        self.packet_count += 1
        self.hw_cycles += int(hw_cycles)
        self.mmio_retries += int(mmio_retries)
        self.mmio_fails += int(mmio_fails)
        self.counts_per_second = int(cps)
        return c16


def load_model(path: Path) -> Dict[str, object]:
    model = json.loads(path.read_text())
    if "layers" not in model or not isinstance(model["layers"], list) or len(model["layers"]) < 1:
        raise ValueError(f"{path}: expected 'layers' list with >=1 entries")
    return model


def transpose_w(w_out_in: Sequence[Sequence[int]]) -> List[List[int]]:
    out_dim = len(w_out_in)
    in_dim = len(w_out_in[0]) if out_dim else 0
    wt = [[0 for _ in range(out_dim)] for _ in range(in_dim)]
    for o in range(out_dim):
        row = w_out_in[o]
        if len(row) != in_dim:
            raise ValueError("weight rows have inconsistent lengths")
        for i in range(in_dim):
            wt[i][o] = int(row[i])
    return wt


def linear_requant(
    acc: Sequence[int],
    bias: Sequence[int],
    scale_in: float,
    scale_w: float,
    scale_out: float,
    zp_out: int,
    relu: bool,
) -> List[int]:
    m = (scale_in * scale_w) / scale_out
    out: List[int] = []
    for j in range(len(acc)):
        v = int(acc[j]) + int(bias[j])
        q = int(round(v * m)) + int(zp_out)
        q = clamp_i8(q)
        if relu and q < 0:
            q = 0
        out.append(q)
    return out


def infer_one_hw(
    client: UartSystolicClient,
    model: Dict[str, object],
    x_q: List[int],
) -> Tuple[int, List[float]]:
    layers = model["layers"]  # type: ignore[index]
    if client.cached_model_loaded and (len(x_q) == client.cached_input_dim):
        l_last = layers[-1]
        pred_cached, logits_i32, _ = client.infer_cached(x_q)
        if bool(l_last.get("output_requant", False)):
            logits_cached = [float(v) for v in logits_i32]
        else:
            m_last = float(l_last["scale_in"]) * float(l_last["scale_w"])
            logits_cached = [float(v) * m_last for v in logits_i32]
        return pred_cached, logits_cached

    act: List[int] = [int(v) for v in x_q]
    last_idx = len(layers) - 1
    logits: List[float] = []
    for li, layer in enumerate(layers):
        w = layer["w"]
        b = layer["b"]
        w_t = transpose_w(w)
        acc = client.matmul_tiled([act], w_t)[0]
        if li != last_idx:
            activation = str(layer.get("activation", "relu")).lower()
            act = linear_requant(
                acc,
                b,
                float(layer["scale_in"]),
                float(layer["scale_w"]),
                float(layer["scale_out"]),
                int(layer.get("zp_out", 0)),
                relu=(activation == "relu"),
            )
        else:
            if bool(layer.get("output_requant", False)):
                activation = str(layer.get("activation", "none")).lower()
                q = linear_requant(
                    acc,
                    b,
                    float(layer["scale_in"]),
                    float(layer["scale_w"]),
                    float(layer["scale_out"]),
                    int(layer.get("zp_out", 0)),
                    relu=(activation == "relu"),
                )
                logits = [float(v) for v in q]
            else:
                m = float(layer["scale_in"]) * float(layer["scale_w"])
                for j in range(len(acc)):
                    v = int(acc[j]) + int(b[j])
                    logits.append(v * m)

    pred = argmax(logits) if logits else -1
    return pred, logits


def infer_one_sw(
    model: Dict[str, object],
    x_q: List[int],
) -> int:
    layers = model["layers"]  # type: ignore[index]
    act: List[int] = [int(v) for v in x_q]
    last_idx = len(layers) - 1
    logits: List[float] = []
    for li, layer in enumerate(layers):
        w = layer["w"]
        b = layer["b"]
        acc = [0] * len(w)
        for o in range(len(w)):
            s = int(b[o])
            row = w[o]
            for i in range(len(act)):
                s += int(act[i]) * int(row[i])
            acc[o] = s

        if li != last_idx:
            activation = str(layer.get("activation", "relu")).lower()
            act = linear_requant(
                acc,
                [0] * len(acc),
                float(layer["scale_in"]),
                float(layer["scale_w"]),
                float(layer["scale_out"]),
                int(layer.get("zp_out", 0)),
                relu=(activation == "relu"),
            )
        else:
            if bool(layer.get("output_requant", False)):
                activation = str(layer.get("activation", "none")).lower()
                q = linear_requant(
                    acc,
                    [0] * len(acc),
                    float(layer["scale_in"]),
                    float(layer["scale_w"]),
                    float(layer["scale_out"]),
                    int(layer.get("zp_out", 0)),
                    relu=(activation == "relu"),
                )
                logits = [float(v) for v in q]
            else:
                m = float(layer["scale_in"]) * float(layer["scale_w"])
                logits = [float(v) * m for v in acc]

    return argmax(logits) if logits else -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="UART port, e.g. /dev/ttyUSB1")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--udp-host", type=str, help="FPGA IPv4 for UDP mode, e.g. 192.168.1.77")
    ap.add_argument("--udp-port", type=int, default=9001, help="FPGA UDP port (default: 9001)")
    ap.add_argument("--udp-local-ip", type=str, default="0.0.0.0", help="local source IPv4 to bind")
    ap.add_argument("--udp-local-port", type=int, default=0, help="optional local UDP port to bind")
    ap.add_argument("--udp-retries", type=int, default=2, help="UDP retries on timeout (default: 2)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--model", type=Path, default=Path("/home/sra-admin/riscv-gpu/mnist_int8.json"))
    ap.add_argument(
        "--images",
        type=Path,
        default=Path("/home/sra-admin/riscv-gpu/data/MNIST/raw/t10k-images-idx3-ubyte"),
    )
    ap.add_argument(
        "--labels",
        type=Path,
        default=Path("/home/sra-admin/riscv-gpu/data/MNIST/raw/t10k-labels-idx1-ubyte"),
    )
    ap.add_argument("--start-index", type=int, default=0)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--verify-sw", action="store_true")
    ap.add_argument("--no-cache-model", action="store_true", help="disable on-device model cache; use GEMM streaming")
    ap.add_argument(
        "--allow-stream-fallback",
        action="store_true",
        help="allow host-side GEMM streaming if cached model load is unavailable",
    )
    args = ap.parse_args()

    if (args.udp_host is None) and (serial is None):
        print(f"pyserial import failed: {SERIAL_IMPORT_ERROR}")
        return 2

    model = load_model(args.model)
    layers = model["layers"]  # type: ignore[index]
    in_len = len(layers[0]["w"][0])
    side = int(round(math.sqrt(in_len)))
    if side * side != in_len:
        raise ValueError(f"model input length {in_len} is not square")

    img_data, img_count, src_h, src_w = read_idx_images(args.images)
    lbl_data, lbl_count = read_idx_labels(args.labels)
    count = min(img_count, lbl_count)
    if count == 0:
        raise ValueError("no samples available")

    input_scale = float(model.get("input_scale", 1.0 / 127.0))
    input_zp = int(model.get("input_zp", 0))

    if args.udp_host:
        client = UdpSystolicClient(
            args.udp_host,
            args.udp_port,
            args.timeout,
            args.udp_local_port,
            args.udp_local_ip,
            args.udp_retries,
        )
        print(f"transport=udp host={args.udp_host}:{args.udp_port} src={client.src_endpoint}")
    else:
        if not args.port:
            raise ValueError("UART mode requires --port (or use --udp-host for Ethernet mode)")
        client = UartSystolicClient(args.port, args.baud, args.timeout)
        print(f"transport=uart port={args.port} baud={args.baud}")
    try:
        if args.no_cache_model and not args.allow_stream_fallback:
            print("fatal: --no-cache-model conflicts with required cached-model mode.")
            print("use cached mode (remove --no-cache-model) or pass --allow-stream-fallback")
            return 4

        if not args.no_cache_model:
            try:
                client.load_model_cached(model)
                print(
                    "cached_model=enabled "
                    f"layers={client.cached_layer_count} "
                    f"in_dim={client.cached_input_dim} out_dim={client.cached_output_dim}"
                )
            except Exception as exc:
                print(f"cached_model=disabled reason={exc}")
                if not args.allow_stream_fallback:
                    if args.udp_host and isinstance(exc, TimeoutError):
                        print("fatal: no UDP response from FPGA. Use UART mode or flash UDP-enabled firmware.")
                    else:
                        print("fatal: cached model load required. Fix model/firmware mismatch or pass --allow-stream-fallback")
                    return 3
        else:
            print("cached_model=disabled reason=--no-cache-model")

        correct = 0
        sw_match = 0
        total_packets = 0
        total_cycles = 0
        total_ms = 0.0

        for t in range(args.count):
            idx = (args.start_index + t) % count
            off = idx * src_h * src_w
            src = img_data[off : off + (src_h * src_w)]
            label = int(lbl_data[idx])

            resized = resize_gray_nn(src, src_h, src_w, side, side)
            x_q: List[int] = []
            for px in resized:
                x_real = float(px) / 255.0
                q = int(round(x_real / input_scale)) + input_zp
                x_q.append(clamp_i8(q))

            client.reset_stats()
            t0 = time.time()
            pred, logits = infer_one_hw(client, model, x_q)
            t1 = time.time()

            if pred == label:
                correct += 1

            sw_note = ""
            if args.verify_sw:
                sw_pred = infer_one_sw(model, x_q)
                ok = sw_pred == pred
                if ok:
                    sw_match += 1
                sw_note = f" sw_pred={sw_pred} hw_sw_match={int(ok)}"

            ms = (t1 - t0) * 1000.0
            total_ms += ms
            total_packets += client.packet_count
            total_cycles += client.hw_cycles

            print(
                f"sample={idx} label={label} pred={pred} "
                f"logit_max={(max(logits) if logits else float('nan')):.6f} packets={client.packet_count} "
                f"hw_cycles={client.hw_cycles} time_ms={ms:.3f}{sw_note}"
            )

        print("----- SUMMARY -----")
        print(f"samples={args.count} correct={correct} accuracy={correct/max(args.count,1):.4f}")
        if args.verify_sw:
            print(f"hw_vs_sw_match={sw_match}/{args.count}")
        print(f"avg_packets={total_packets/max(args.count,1):.2f}")
        print(f"avg_hw_cycles={total_cycles/max(args.count,1):.2f}")
        if client.counts_per_second and client.counts_per_second > 0:
            avg_hw_ms = (total_cycles / client.counts_per_second) * 1000.0 / max(args.count, 1)
            print(f"avg_hw_time_ms_from_cycles={avg_hw_ms:.3f}")
        print(f"avg_end_to_end_ms={total_ms/max(args.count,1):.3f}")
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
