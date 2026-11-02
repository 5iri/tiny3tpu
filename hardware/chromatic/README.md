# tiny3tpu banana on ModRetro Chromatic

A standalone FPGA demo for the Chromatic's **GW5A-25A**. The existing
[`tpu_core_wrapper`](../../multi-core/tpu_core_wrapper.sv),
[`systolic_array`](../../systolic_array/rtl/NxN_systolic_array.v), and
[`pe`](../../systolic_array/rtl/pe.v) perform the banana's live matrix products.
An RTL renderer generates pixels directly for the handheld's 160×144 LCD.

This target instantiates **one 4×4 INT8 core with INT32 accumulators**. Each
frame uses 51 GEMMs to transform 204 vertices, followed by 407 triangles. There
is no CPU, UART rendering host, Game Boy ROM, or recorded animation in this
image. It is a dedicated controller around the tiny3tpu accelerator, rather
than a port of the KC705 VexRiscv/StableHLO runtime.

## Controls

| Button | Action |
| --- | --- |
| A | Pause / resume automatic rotation |
| B | Reverse automatic rotation |
| Left / right | Rotate manually, including while paused |
| Up / down | Set rotation speed, 1–4 |
| Start or Select | Return to the initial angle |

The footer displays pause/direction, speed, the displayed angle index in hex,
and **CYC**, the last render's clock count in hex. CYC includes framebuffer
clear, TPU operand transfers/compute/readback, and triangle rasterization. It
excludes waiting for vertical blank. The clock is 33.554432 MHz. `51 GEMM`
means accelerator launches per frame, not a throughput measurement.

## Build, verify, load

From this directory:

```sh
make lint test
make CAD=/path/to/oss-cad-suite
make load CAD=/path/to/oss-cad-suite
```

`CAD` defaults to the existing sibling `fun/pikachu/.tools/oss-cad-suite`
installation in this workspace. The flow uses Yosys's `gw5a` synthesis,
nextpnr-himbaechel, and `gowin_pack`, targeting `GW5A-EV25UG256CC1/I0`.
Simulation requires Python 3, Icarus, Verilator and a C++ compiler. Pillow is
optional for the preview GIF; the checks and PPM images work without it.

`make load` uses `openFPGALoader --cable gwu2x --freq 1000000 --write-sram`.
It loads volatile FPGA SRAM. Fully power-cycle the handheld, disconnecting USB,
to restore the boot image. The custom demo disables audio, MCU, cartridge,
PSRAM, link, and USB data functions while running; its computer connection is
not a video feed. It retains the existing board layer's idle pin levels.

Outputs under ignored `build/`:

- `banana.fs`: loadable FPGA image.
- `synthesis.log`, `place-route.log`, `timing.json`: resource/timing evidence.
- `verification.json`: simulated render-cycle counts and check totals.
- `frame-*.ppm`, `preview.png`, `banana-rtl.gif`: pixels captured from RTL
  simulation, without the LCD text overlay. GIF playback is illustrative.
- `renderer-test.log`, `scene-test.log`, `display-test.log`: test results.

The current Yosys version leaves `$buf` aliases on some partially used INT32
results. A final `techmap` restricted to `$buf` cells converts these aliases to direct connections before
nextpnr; it does not change the accelerator RTL. `verilator.vlt` suppresses
only the existing generic core's intentional integer-widening warnings.
The small triangle-index ROM is forced to logic after its single-port BSRAM
mapping failed routed address hold checks. Pixel, depth, and projected-vertex
storage retain synchronous block RAM.

## Rendering and verification scope

Vertices are centered and quantized to ±110. A ROM supplies 256 INT8 rotation
matrices, tilted by 20 degrees; the TPU calculates transformed vertices anew
on every frame. Orthographic projection uses shifts. Triangle coverage uses
incremental signed edge equations, and a depth buffer selects the closest
triangle using **one average depth per face**. Lighting is baked in object
space. This deliberately simple renderer can show faceted shading and depth
artifacts; it does not implement the host demo's perspective or SoftRas.

Color uses two 32K×4-bit framebuffer banks; depth uses one 32K×8-bit buffer.
Only 23,040 entries per bank are active. A completed color buffer becomes
visible only at vertical blank, so scanout never displays a partial render.
All 256 projection positions are checked to stay inside the render area.

`make test` checks 16 angles with an independent scalar matrix multiply and
direct (non-incremental) edge-function rasterizer:

- All **9,792 INT32 coordinates**, **368,640 pixels**, and 816 actual TPU
  launches, including reset during work and an extra START while busy.
- Publication only after completion and at vertical blank; pause, manual
  rotation, opposing buttons, speed limits, reverse/wrap and home/reset.
- Both synchronous framebuffer banks through LCD scanout, including writes
  to the back buffer while displaying the front, black controller padding,
  and **138,240 visible RGB components** across two frames.

Simulation checks are distinct from physical display verification. See the
generated logs and any hardware observation recorded below.

## Build and hardware result — 2026-10-04

The final route completed with **zero errors and no hold violations**, passing
the 33.555 MHz constraint. Its reported maximum clock is 90.88 MHz; the demo
runs at the board's normal 33.554432 MHz. The timing report lists 9,533 LUT4s,
1,548 flip-flops, 1,340 ALU cells, and 34 of 56 BSRAM blocks. The one routing
warning is the left-button input falling back to ordinary data routing.

The 16 tested frames take **53,449–93,402 clocks (1.59–2.78 ms)** in RTL
simulation. Publication is paced by the approximately 58.22 Hz LCD scan.
These are simulated compute times, not physical timing measurements.

JTAG detected the attached Chromatic (`0x1281b`) and `make load` completed the
SRAM transfer successfully. `build/load.log` records the loader's completion;
`build/hardware.json` records the image/source hashes and timing report.
The user confirmed **“Yes, it’s rotating”** on the physical Chromatic after
this load. Button behavior is covered by simulation; it has not been separately
confirmed on the handheld. The preview images remain simulation captures.

## Sources

The mesh is the same 204-vertex reduction used by
[`sidequests/banana`](../../sidequests/banana), derived from
[SRA-VJTI/jaxsim's banana](https://github.com/SRA-VJTI/jaxsim/blob/c0a097bba1c6db10cac7b359fbac11cfedc48c6b/examples/sampledata/banana.obj).
`assets/mesh.json` records the source and centered INT8 geometry;
`python3 tools/assets.py` regenerates the three checked-in ROM files using
only Python's standard library.

The panel initialization, scanout, buttons, font, safe peripheral states, and
constraints are adapted from this workspace's `fun/pikachu/rtl-fractal`.
Its board reference is
[ModRetro's FPGA source at `8b4c965`](https://github.com/ModRetro/oss-chromatic-console-fpga/tree/8b4c965dc3a57fd4412836c136b5228a63c72803).
The GPL-3.0 license for that board material is retained in
[`reference/MODRETRO-LICENSE.txt`](reference/MODRETRO-LICENSE.txt).
