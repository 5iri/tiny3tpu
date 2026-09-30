#!/usr/bin/env python3
"""Render verified KC705 vertex responses and serve a live FPS dashboard."""
import argparse
import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import struct
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/cu.usbserial-0001")
    parser.add_argument("--baud", type=int, default=921600,
                        help="UART rate matching live_firmware.c (older image: 115200)")
    parser.add_argument("--jaxsim", type=Path, required=True)
    parser.add_argument("--render", type=Path, default=ROOT / "build-banana/render")
    parser.add_argument("--out", type=Path, default=ROOT / "build-banana/live")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--frames", type=int, default=0, help="0 runs continuously")
    parser.add_argument("--uart-byte-gap", type=float, default=0.0,
                        help="Seconds between request bytes for reliable UART RX")
    parser.add_argument("--frame-gap", type=float, default=0.0,
                        help="Seconds of UART idle time between frame requests")
    args = parser.parse_args()
    import jax
    import jax.numpy as jnp
    import numpy as np
    from PIL import Image
    import serial
    sys.path.insert(0, str(args.jaxsim.resolve()))
    from jaxsim.renderutils import SoftRenderer
    from render import camera_rotation, ROTATION_SCALE
    args.out.mkdir(parents=True, exist_ok=True)
    mesh = np.load(args.render / "mesh.npz")
    report = json.loads((args.render / "report.json").read_text())
    vertex_scale = report["vertex_scale"]
    vertices, faces = mesh["vertices"], mesh["faces"]
    inputs = np.rint(vertices * vertex_scale).astype(np.int8)
    renderer = SoftRenderer(image_size=64, anti_aliasing=False, camera_mode="look_at")
    world, indices = jnp.asarray(vertices[None]), jnp.asarray(faces[None])
    textures = jnp.broadcast_to(jnp.array([1., 1., 0.]), (1, len(faces), 3))
    lit = renderer.lighting(world, indices, textures[:, :, None, :])[:, :, 0, :]
    rasterize = jax.jit(lambda camera: renderer.rasterize(
        renderer.perspective_distortion(camera, renderer.viewing_angle), indices, lit))
    renderer.set_eye_from_angles(2., 30., 0.)
    rasterize(renderer.look_at(world, renderer.eye)).block_until_ready()
    state = {"connected": False, "message": "Waiting for first KC705 frame", "sequence": -1}
    lock = threading.Lock()
    page = Path(__file__).with_name("live.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path.startswith("/live"):
                payload, mime = page, "text/html"
            elif self.path.startswith("/state"):
                with lock:
                    snapshot = dict(state)
                snapshot["age_seconds"] = time.time() - snapshot.get("timestamp", time.time())
                payload, mime = json.dumps(snapshot).encode(), "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *unused):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", args.http_port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Live dashboard: http://127.0.0.1:{args.http_port}", flush=True)
    history = deque(maxlen=16)
    log = (args.out / "frames.jsonl").open("a", buffering=1)
    previous = None
    sequence = 0
    executor = ThreadPoolExecutor(max_workers=1)
    # UART reads wait for the board indefinitely; the dashboard runs separately.
    try:
        with serial.Serial(args.port, args.baud, timeout=None, write_timeout=3) as device:
            device.reset_input_buffer()
            def read_exact(count):
                data = bytearray()
                while len(data) < count:
                    data.extend(device.read(count - len(data)))
                return bytes(data)
            def prepare(sequence):
                started = time.perf_counter()
                angle = sequence * 12.0 % 360.0
                renderer.set_eye_from_angles(2., 30., angle)
                rotation = camera_rotation(renderer, jnp, np)
                weights = np.rint(rotation * ROTATION_SCALE).astype(np.int8)
                bias = np.rint(-np.asarray(renderer.eye) @ rotation * vertex_scale * ROTATION_SCALE).astype(np.int32)
                expected = inputs.astype(np.int32) @ weights.astype(np.int32) + bias
                request = b"BNQ1" + struct.pack("<I", sequence) + weights.tobytes() + bias.astype("<i4").tobytes()
                return sequence, angle, started, request, expected

            def transact(sequence, angle, started, request, expected):
                if sequence and args.frame_gap:
                    time.sleep(args.frame_gap)
                wire_start = time.perf_counter()
                if args.uart_byte_gap:
                    for byte in request:
                        device.write(bytes([byte]))
                        device.flush()
                        time.sleep(args.uart_byte_gap)
                else:
                    device.write(request)
                device.flush()
                sync = read_exact(4)
                while sync != b"BNR1":
                    sync = sync[1:] + read_exact(1)
                received_seq, status, cycles, count, checksum = struct.unpack("<IIIII", read_exact(20))
                if received_seq != sequence or status or count != len(vertices):
                    raise RuntimeError(f"bad response seq={received_seq} status={status} count={count}")
                data = read_exact(count * 12)
                roundtrip_ms = (time.perf_counter() - wire_start) * 1000
                actual = np.frombuffer(data, dtype="<i4").reshape(count, 3)
                if int(np.bitwise_xor.reduce(actual.reshape(-1).view(np.uint32))) != checksum:
                    raise RuntimeError("UART checksum mismatch")
                if not np.array_equal(actual, expected):
                    raise RuntimeError("KC705 transform differs from integer reference")
                return angle, started, actual, cycles, count, roundtrip_ms

            pending = executor.submit(transact, *prepare(sequence))
            while not args.frames or sequence < args.frames:
                with lock:
                    state.update(waiting=True, message="Waiting for UART")
                angle, started, actual, cycles, count, roundtrip_ms = pending.result()
                # One outstanding request: its UART/TPU work overlaps rendering
                # this verified frame, preserving every frame in sequence.
                if not args.frames or sequence + 1 < args.frames:
                    pending = executor.submit(transact, *prepare(sequence + 1))
                render_start = time.perf_counter()
                camera = actual.astype(np.float32) / (vertex_scale * ROTATION_SCALE)
                rgba = np.asarray(rasterize(jnp.asarray(camera[None])))[0].transpose(1, 2, 0)
                if not np.isfinite(rgba).all():
                    raise RuntimeError("nonfinite rendered image")
                pixels = np.rint(np.clip(rgba[..., :3], 0, 1) * 255).astype(np.uint8)
                image = Image.fromarray(pixels)
                png = io.BytesIO()
                image.save(png, format="PNG")
                image_bytes = png.getvalue()
                host_render_ms = (time.perf_counter() - render_start) * 1000
                completed = time.perf_counter()
                if previous is not None:
                    history.append(completed - previous)
                previous = completed
                compute_ms = cycles / 100000.0
                item = {"connected": True, "waiting": False, "sequence": sequence, "timestamp": time.time(),
                        "fps": len(history) / sum(history) if history else 1000 / ((completed - started) * 1000),
                        "frame_ms": (completed - started) * 1000,
                        "fpga_compute_ms": compute_ms, "uart_roundtrip_ms": roundtrip_ms,
                        "uart_and_host_wait_ms": max(0, roundtrip_ms - compute_ms),
                        "host_render_ms": host_render_ms, "cycles": cycles, "azimuth": angle,
                        "vertices": count, "verified": True, "port": args.port, "baud": args.baud,
                        "message": "Physical KC705 / no DDR / exact integer match"}
                log.write(json.dumps(item) + "\n")
                (args.out / "latest.png").write_bytes(image_bytes)
                (args.out / "latest.json").write_text(json.dumps(item, indent=2) + "\n")
                with lock:
                    state.update(item, png=base64.b64encode(image_bytes).decode())
                if sequence % 10 == 0:
                    print(f"frame={sequence} FPS={item['fps']:.2f} FPGA={compute_ms:.2f}ms "
                          f"UART+wait={item['uart_and_host_wait_ms']:.2f}ms render={host_render_ms:.2f}ms verified", flush=True)
                sequence += 1
    except Exception as exc:
        with lock:
            state.update(connected=False, message=str(exc))
        print(f"LIVE STOPPED: {exc}", flush=True)
        # Keep the error visible in the browser instead of silently replaying old frames.
        while True:
            time.sleep(1)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        log.close()
    server.shutdown()

if __name__ == "__main__":
    main()
