#!/usr/bin/env python3
"""
Pygame MNIST drawing demo over the 16x16 systolic firmware binary protocol.

Draw a digit on the canvas with left mouse, release to run inference.
The stroke is rendered into a centered/scaled MNIST-style grid (from fpgademo
pipeline), then quantized and sent over UART/UDP using the same packet path as
mnist_infer_uart.py.

Protocol in use:
  - Cached inference path: MOD1 model upload + INF1 input vectors + PRD1 outputs
  - Streaming fallback path: MAT1/RSP1 tiled GEMM packets
"""

from __future__ import annotations

import argparse
import math
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import pygame  # type: ignore
except Exception as exc:  # pragma: no cover
    pygame = None
    PYGAME_IMPORT_ERROR = exc
else:
    PYGAME_IMPORT_ERROR = None

try:
    from mnist_infer_uart import (  # type: ignore
        BIN_REQ_MODEL_MAGIC,
        BIN_REQ_INFER_MAGIC,
        BIN_RESP_INFER_MAGIC,
        UartSystolicClient,
        UdpSystolicClient,
        clamp_i8,
        infer_one_hw,
        infer_one_sw,
        load_model,
    )
except Exception:
    from app_component.tools.mnist_infer_uart import (  # type: ignore
        BIN_REQ_MODEL_MAGIC,
        BIN_REQ_INFER_MAGIC,
        BIN_RESP_INFER_MAGIC,
        UartSystolicClient,
        UdpSystolicClient,
        clamp_i8,
        infer_one_hw,
        infer_one_sw,
        load_model,
    )


Color = Tuple[int, int, int]
Point = Tuple[int, int]
FloatPoint = Tuple[float, float]


BG: Color = (13, 16, 20)
PANEL_BG: Color = (22, 27, 34)
CANVAS_BG: Color = (6, 9, 12)
CANVAS_BORDER: Color = (70, 86, 102)
INK: Color = (19, 210, 233)
TEXT: Color = (240, 245, 250)
SUBTEXT: Color = (170, 182, 196)


def normalize_points(points: Sequence[Point], w: int, h: int) -> List[FloatPoint]:
    if w <= 1 or h <= 1:
        return []
    return [(x / float(w - 1), y / float(h - 1)) for (x, y) in points]


def render_stroke_to_grid(
    points: Sequence[FloatPoint],
    grid: int,
    thickness: int = 2,
    supersample: int = 8,
    border_frac: float = 0.1,
    intensity_step: int = 255,
) -> List[int]:
    """
    Render normalized stroke points into a grid x grid grayscale image [0..127].
    Ported from the fpgademo branch preprocessing pipeline.
    """
    if not points:
        return [0] * (grid * grid)

    ss = max(2, supersample)
    hi = grid * ss
    canvas = [[0 for _ in range(hi)] for _ in range(hi)]

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    span_x = max(1e-6, xmax - xmin)
    span_y = max(1e-6, ymax - ymin)
    span = max(span_x, span_y)
    fill_frac = max(0.6, min(0.9, 1.0 - 2 * border_frac))
    target_span = fill_frac * hi
    scale = target_span / span
    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0

    def to_grid(pt: FloatPoint) -> Tuple[float, float]:
        gx = (pt[0] - cx) * scale + (hi - 1) / 2.0
        gy = (pt[1] - cy) * scale + (hi - 1) / 2.0
        return gx, gy

    def stamp_circle(cx_px: float, cy_px: float, radius: float) -> None:
        r = max(0.0, radius)
        r_int = max(1, int(math.ceil(r)))
        r2 = r * r
        y0 = max(0, int(math.floor(cy_px - r_int)))
        y1 = min(hi - 1, int(math.ceil(cy_px + r_int)))
        x0 = max(0, int(math.floor(cx_px - r_int)))
        x1 = min(hi - 1, int(math.ceil(cx_px + r_int)))
        for yy in range(y0, y1 + 1):
            dy = yy - cy_px
            for xx in range(x0, x1 + 1):
                dx = xx - cx_px
                if dx * dx + dy * dy <= r2:
                    val = canvas[yy][xx] + intensity_step
                    canvas[yy][xx] = 255 if val > 255 else val

    radius = max(0.5, float(thickness))
    for i in range(len(points)):
        p0 = points[i - 1] if i > 0 else points[i]
        p1 = points[i]
        x0, y0 = to_grid(p0)
        x1, y1 = to_grid(p1)
        dx = x1 - x0
        dy = y1 - y0
        seg_len = max(1.0, math.hypot(dx, dy))
        steps = int(seg_len) + 1
        for s in range(steps + 1):
            t = s / steps if steps else 0.0
            cx_px = x0 + dx * t
            cy_px = y0 + dy * t
            stamp_circle(cx_px, cy_px, radius)

    block = hi // grid
    flat: List[int] = []
    max_val = 0
    for gy in range(grid):
        for gx in range(grid):
            acc = 0
            count = 0
            for yy in range(gy * block, min((gy + 1) * block, hi)):
                for xx in range(gx * block, min((gx + 1) * block, hi)):
                    acc += canvas[yy][xx]
                    count += 1
            val = acc // max(1, count)
            flat.append(val)
            if val > max_val:
                max_val = val

    if max_val > 0:
        return [min(127, max(0, int(round(v * 127.0 / max_val)))) for v in flat]
    return [0] * (grid * grid)


def quantize_input(grid_vals: Sequence[int], input_scale: float, input_zp: int) -> List[int]:
    out: List[int] = []
    for px in grid_vals:
        x_real = float(px) / 127.0
        q = int(round(x_real / input_scale)) + input_zp
        out.append(clamp_i8(q))
    return out


def draw_grid_preview(
    screen: "pygame.Surface",
    grid_vals: Sequence[int],
    side: int,
    top_left: Tuple[int, int],
    cell_px: int,
) -> None:
    x0, y0 = top_left
    width = side * cell_px
    height = side * cell_px
    pygame.draw.rect(screen, (58, 70, 82), (x0 - 2, y0 - 2, width + 4, height + 4), width=1)
    for r in range(side):
        for c in range(side):
            v = int(max(0, min(127, grid_vals[r * side + c])))
            g = int(round(v * 255.0 / 127.0))
            col = (g, g, g)
            pygame.draw.rect(screen, col, (x0 + c * cell_px, y0 + r * cell_px, cell_px, cell_px))


def render_text_lines(
    screen: "pygame.Surface",
    font: "pygame.font.Font",
    lines: Sequence[str],
    x: int,
    y: int,
    color: Color,
    line_h: int = 22,
) -> None:
    for i, line in enumerate(lines):
        screen.blit(font.render(line, True, color), (x, y + i * line_h))


def main() -> int:
    ap = argparse.ArgumentParser(description="Draw-and-infer MNIST demo over systolic array (UART/UDP)")
    ap.add_argument("--port", help="UART port, e.g. /dev/ttyUSB1")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--udp-host", type=str, help="FPGA IPv4 for UDP mode, e.g. 192.168.1.77")
    ap.add_argument("--udp-port", type=int, default=9001, help="FPGA UDP port (default: 9001)")
    ap.add_argument("--udp-local-ip", type=str, default="0.0.0.0", help="local source IPv4 to bind")
    ap.add_argument("--udp-local-port", type=int, default=0, help="optional local UDP port to bind")
    ap.add_argument("--udp-retries", type=int, default=2, help="UDP retries on timeout (default: 2)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--model", type=Path, default=Path("/home/sra-admin/riscv-gpu/mnist_int8.json"))
    ap.add_argument("--size", type=int, default=560, help="draw canvas size in pixels")
    ap.add_argument("--thickness", type=int, default=2, help="stroke thickness used in render")
    ap.add_argument("--supersample", type=int, default=8, help="render supersampling factor")
    ap.add_argument("--border-frac", type=float, default=0.10, help="border fraction in render")
    ap.add_argument("--intensity-step", type=int, default=255, help="intensity added per stamped point")
    ap.add_argument("--line-width", type=int, default=10, help="onscreen stroke line width")
    ap.add_argument("--verify-sw", action="store_true", help="also run software quantized inference")
    ap.add_argument(
        "--allow-stream-fallback",
        action="store_true",
        help="allow host-side GEMM streaming if cached model load is unavailable",
    )
    ap.add_argument("--fps", type=int, default=60)
    args = ap.parse_args()

    if pygame is None:
        raise RuntimeError(f"pygame import failed: {PYGAME_IMPORT_ERROR}")

    model = load_model(args.model)
    layers = model["layers"]  # type: ignore[index]
    input_len = len(layers[0]["w"][0])
    grid_side = int(round(math.sqrt(input_len)))
    if grid_side * grid_side != input_len:
        raise ValueError(f"model input length {input_len} is not square")
    input_scale = float(model.get("input_scale", 1.0 / 127.0))
    input_zp = int(model.get("input_zp", 0))

    panel_w = max(360, grid_side * 12 + 60)
    win_w = args.size + panel_w + 36
    win_h = max(args.size + 24, 520)

    pygame.init()
    screen = pygame.display.set_mode((win_w, win_h))
    pygame.display.set_caption("MNIST Draw UART Inference")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("DejaVu Sans", 20)
    small = pygame.font.SysFont("DejaVu Sans", 16)

    canvas_rect = pygame.Rect(16, 12, args.size, args.size)
    panel_rect = pygame.Rect(canvas_rect.right + 12, 12, panel_w, win_h - 24)

    if args.udp_host:
        client = UdpSystolicClient(
            args.udp_host,
            args.udp_port,
            args.timeout,
            args.udp_local_port,
            args.udp_local_ip,
            args.udp_retries,
        )
        transport_line = f"transport: udp {args.udp_host}:{args.udp_port} src={client.src_endpoint}"
    else:
        if not args.port:
            raise ValueError("UART mode requires --port (or use --udp-host for Ethernet mode)")
        client = UartSystolicClient(args.port, args.baud, args.timeout)
        transport_line = f"transport: uart {args.port} @ {args.baud}"

    stroke: List[Point] = []
    drawing = False
    prediction = "-"
    sw_prediction = "-"
    logits: List[float] = []
    last_grid: List[int] = [0] * (grid_side * grid_side)
    status = "loading-model"
    mode_line = "mode: loading cached-model..."
    timing_line = "packets=0 cycles=0 ms=0.000"
    err_line = ""
    model_ready = False
    model_load_failed = False

    inference_thread: Optional[threading.Thread] = None
    pending: Optional[Dict[str, object]] = None
    model_load_thread: Optional[threading.Thread] = None
    model_load_result: Optional[Dict[str, object]] = None

    try:
        def model_loader() -> None:
            nonlocal model_load_result
            try:
                client.load_model_cached(model)
                model_load_result = {
                    "ok": True,
                    "fallback": False,
                    "mode_line": (
                        f"mode: cached-model ({client.cached_layer_count}L "
                        f"{client.cached_input_dim}->{client.cached_output_dim})"
                    ),
                    "err": "",
                }
            except Exception as exc:
                if args.allow_stream_fallback:
                    model_load_result = {
                        "ok": True,
                        "fallback": True,
                        "mode_line": f"mode: stream ({len(layers)} layers)",
                        "err": f"cache load failed: {exc}",
                    }
                else:
                    model_load_result = {
                        "ok": False,
                        "fallback": False,
                        "mode_line": "mode: cache-load-failed",
                        "err": (
                            f"cached model load failed: {exc}. "
                            "Fix firmware/model path or pass --allow-stream-fallback."
                        ),
                    }

        model_load_thread = threading.Thread(target=model_loader, daemon=True)
        model_load_thread.start()
        running = True
        while running:
            if model_load_thread and (not model_load_thread.is_alive()):
                model_load_thread = None
                if model_load_result is not None:
                    mode_line = str(model_load_result.get("mode_line", mode_line))
                    err_line = str(model_load_result.get("err", ""))
                    if bool(model_load_result.get("ok", False)):
                        model_ready = True
                        model_load_failed = False
                        status = "idle"
                    else:
                        model_ready = False
                        model_load_failed = True
                        status = "error"
                    model_load_result = None

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_q, pygame.K_ESCAPE):
                        running = False
                    elif event.key == pygame.K_c:
                        stroke.clear()
                        prediction = "-"
                        sw_prediction = "-"
                        logits = []
                        last_grid = [0] * (grid_side * grid_side)
                        status = "cleared"
                        timing_line = "packets=0 cycles=0 ms=0.000"
                        err_line = ""
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if canvas_rect.collidepoint(event.pos):
                        drawing = True
                        lx = max(0, min(args.size - 1, event.pos[0] - canvas_rect.x))
                        ly = max(0, min(args.size - 1, event.pos[1] - canvas_rect.y))
                        stroke = [(lx, ly)]
                elif event.type == pygame.MOUSEMOTION and drawing:
                    lx = max(0, min(args.size - 1, event.pos[0] - canvas_rect.x))
                    ly = max(0, min(args.size - 1, event.pos[1] - canvas_rect.y))
                    stroke.append((lx, ly))
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if drawing:
                        drawing = False
                        if not stroke:
                            continue
                        if not model_ready:
                            status = "error" if model_load_failed else "loading-model"
                            continue
                        if inference_thread and inference_thread.is_alive():
                            status = "busy"
                            continue

                        status = "running"
                        err_line = ""
                        stroke_snapshot = stroke[:]

                        def worker() -> None:
                            nonlocal pending
                            try:
                                norm = normalize_points(stroke_snapshot, args.size, args.size)
                                grid = render_stroke_to_grid(
                                    norm,
                                    grid=grid_side,
                                    thickness=args.thickness,
                                    supersample=args.supersample,
                                    border_frac=args.border_frac,
                                    intensity_step=args.intensity_step,
                                )
                                x_q = quantize_input(grid, input_scale, input_zp)

                                client.reset_stats()
                                t0 = time.time()
                                pred, pred_logits = infer_one_hw(client, model, x_q)
                                t1 = time.time()

                                sw_pred: Optional[int] = None
                                if args.verify_sw:
                                    sw_pred = infer_one_sw(model, x_q)

                                pending = {
                                    "pred": pred,
                                    "logits": pred_logits,
                                    "grid": grid,
                                    "ms": (t1 - t0) * 1000.0,
                                    "packets": client.packet_count,
                                    "cycles": client.hw_cycles,
                                    "sw_pred": sw_pred,
                                    "error": "",
                                }
                            except Exception as exc:  # pragma: no cover - runtime path
                                pending = {
                                    "pred": "-",
                                    "logits": [],
                                    "grid": [0] * (grid_side * grid_side),
                                    "ms": 0.0,
                                    "packets": 0,
                                    "cycles": 0,
                                    "sw_pred": None,
                                    "error": str(exc),
                                }

                        inference_thread = threading.Thread(target=worker, daemon=True)
                        inference_thread.start()

            if inference_thread and not inference_thread.is_alive():
                inference_thread = None
                if pending is not None:
                    prediction = str(pending.get("pred", "-"))
                    logits = list(pending.get("logits", []))  # type: ignore[arg-type]
                    last_grid = list(pending.get("grid", last_grid))  # type: ignore[arg-type]
                    ms = float(pending.get("ms", 0.0))
                    packets = int(pending.get("packets", 0))
                    cycles = int(pending.get("cycles", 0))
                    swp = pending.get("sw_pred")
                    sw_prediction = "-" if swp is None else str(int(swp))
                    timing_line = f"packets={packets} cycles={cycles} ms={ms:.3f}"
                    err_line = str(pending.get("error", ""))
                    status = "error" if err_line else "done"
                    pending = None

            screen.fill(BG)
            pygame.draw.rect(screen, CANVAS_BG, canvas_rect)
            pygame.draw.rect(screen, CANVAS_BORDER, canvas_rect, width=2)
            if len(stroke) > 1:
                stroke_global = [(canvas_rect.x + x, canvas_rect.y + y) for (x, y) in stroke]
                pygame.draw.lines(screen, INK, False, stroke_global, args.line_width)

            pygame.draw.rect(screen, PANEL_BG, panel_rect, border_radius=8)
            info_x = panel_rect.x + 12
            info_y = panel_rect.y + 12
            render_text_lines(
                screen,
                font,
                [
                    f"Pred: {prediction}",
                    f"Status: {status}",
                    f"SW Pred: {sw_prediction}" if args.verify_sw else "SW Pred: (disabled)",
                ],
                info_x,
                info_y,
                TEXT,
                line_h=28,
            )

            logits_str = " ".join(f"{v:.3f}" for v in logits[:10]) if logits else "-"
            render_text_lines(
                screen,
                small,
                [
                    mode_line,
                    transport_line,
                    (
                        f"proto: load=0x{BIN_REQ_MODEL_MAGIC:08x} "
                        f"infer=0x{BIN_REQ_INFER_MAGIC:08x} "
                        f"resp=0x{BIN_RESP_INFER_MAGIC:08x}"
                    ),
                    f"logits: {logits_str}",
                    timing_line,
                    "controls: draw + release infer",
                    "c: clear, q/esc: quit",
                ],
                info_x,
                info_y + 96,
                SUBTEXT,
                line_h=22,
            )

            if err_line:
                render_text_lines(screen, small, [f"error: {err_line}"], info_x, info_y + 186, (255, 130, 130), 22)

            preview_cell = max(4, min(16, (panel_rect.w - 24) // max(1, grid_side)))
            preview_x = info_x
            preview_y = panel_rect.y + panel_rect.h - (grid_side * preview_cell) - 16
            draw_grid_preview(screen, last_grid, grid_side, (preview_x, preview_y), preview_cell)
            screen.blit(small.render(f"input matrix ({grid_side}x{grid_side})", True, SUBTEXT), (preview_x, preview_y - 22))

            pygame.display.flip()
            clock.tick(max(1, args.fps))
    finally:
        client.close()
        pygame.quit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
