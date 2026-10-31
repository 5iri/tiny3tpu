# KC705 JAX / CPU / dual-TPU HDMI banana

## CPU-written framebuffer target

The additional `--cpu --framebuffer` target implements a general CPU-pixel path:
compiled JAX → CPU → compiler-selected TPU calls → CPU RGB565 rendering →
double-buffered framebuffer → HDMI. It does not instantiate the triangle
rasterizer. The original mesh target below remains selected by `--cpu` alone.

The first framebuffer configuration is **160×120 RGB565**, scaled 4× to 640×480
at 60 Hz. Each bank holds 38,400 bytes in BRAM. Firmware renders into its own
CPU buffer and uploads 9,600 words in order, with two little-endian RGB565 pixels
per word. A completed upload is queued for publication at vertical blank.
Queued-bank writes and incomplete submissions return bus errors. The front
bank is never CPU-writable, and reset hides memory until a full frame is supplied.

The MuJoCo renderer target uses **320×240 RGB565**, scaled 2×, with 153,600
bytes per display bank and 38,400 upload words. It selects 1 MiB of CPU BRAM;
the original 160×120 fixture keeps 256 KiB. The build reads resolution and RAM
size from the verified firmware manifest and passes matching RTL parameters.

`sidequests/mjx_rl/prepare.py --video-mode 720p` selects **1280×720 at 60 Hz**
with a **480×270 MuJoCo RGB565 image**, 259,200 bytes per bank and 64,800 upload
words. The image has 68.75% more source pixels than the VGA MuJoCo configuration;
nearest-neighbor enlargement maps output `(x,y)` to source `(floor(3x/8),floor(3y/8))`.
This is 720p scanout, not native 720p rendering. The 16:9 viewport uses MuJoCo's
projection at the new aspect ratio rather than stretching a 4:3 frame.

The 720p target uses 1216 KiB of CPU BRAM and a 74.25 MHz shared CPU/video clock.
An MMCME2_ADV generates `200 / 10 × 37.125 / 10 = 74.25 MHz`; the VGA target keeps
its original PLL. The raster has 1650×750 total pixels, positive H/V sync, and
the transmitter advertises VIC 4 / 16:9. I²C dividers follow the selected clock.
The pixel upload protocol and vertical-blank publication are identical in both
modes. Synthesis alone does not establish 74.25 MHz timing closure or physical HDMI.

The complete 720p MuJoCo design synthesizes to 432 RAMB36E1s, four RAMB18E1s
and 42 DSP48E1s (434 of the device's 445 block-RAM equivalents). Both display
banks remain present in the netlist. The build rejects constant-folded scanout
counters or missing display memory as well as block-RAM capacity overflow.

The interface is in `include/tiny3tpu_framebuffer.h`. Control starts at
`0x40000000`, with a separate pixel aperture at `0x40100000`. These addresses
belong to this BRAM target; a future DDR target must avoid overlapping them.

| Control offset | Access | Meaning |
| --- | --- | --- |
| `0x00` | R | ABI ID `0x50464231` (`PFB1`) |
| `0x04` | R | Ready, pending, valid, front-bank bits 0–3 |
| `0x08` | W | Queue completed image with a 32-bit application tag |
| `0x0c` | R | Uploaded word count |
| `0x10`, `0x14` | R | Width and height |
| `0x18` | R | Words per frame |
| `0x1c`, `0x20` | R | Published-frame count and displayed tag |
| `0x24` | R | Pixel format, decimal 565 |
| `0x28`, `0x2c` | R | HDMI active width and height |
| `0x30` | R | Pixel clock in Hz |

Pixel writes must be aligned, full-word writes at the next sequential address;
pixel reads are not implemented. The nonblocking `tiny3tpu_fb_present` readiness
check lets a caller keep computing when an earlier frame is pending.

```sh
.venv/bin/python hardware/kc705_hdmi/tests/test_pixels.py --out build-kc705-hdmi/pixels-unit
.venv/bin/python hardware/kc705_hdmi/tests/test_pixel_cpu.py --out build-kc705-hdmi/pixels-cpu
python3 hardware/kc705_hdmi/build.py synth --cpu --framebuffer \
  --firmware build-kc705-hdmi/pixels-cpu/firmware --out build-kc705-hdmi/pixels-board

# Widescreen scanout and transmitter protocol checks.
python3 hardware/kc705_hdmi/tests/test_pixels.py --video-mode 720p --synth --out build-mjx/720p-synth-pixels
python3 hardware/kc705_hdmi/tb/test_init.py --video-mode 720p --out build-mjx/720p-init
```

The unit check tests protocol errors, backpressure, reset, concurrent upload and
scanout, and external HDMI pixels. The CPU test executes the actual generated
program and generic TPU driver, then checks CPU-rendered images on the HDMI bus.
The small square fixture isolates architecture; it does not claim RL training.
The [actual MJX training workload](https://github.com/5iri/tiny3tpu/blob/feat/mjx-learning/sidequests/mjx_rl/README.md) uses the same
hardware and framebuffer ABI. Synthesis and RTL checks do not prove physical
HDMI timing or board operation.

`--synth` runs the same bus/pixel checks on Yosys's DSP-mapped coarse netlist
using its behavioral DSP48E1 model and inferred memories. This catches a Yosys
0.63 pre-adder packing problem observed when the 3/8 scaler was written as
`h_count * 3`: the shared counter increment lost its driver. The RTL uses
shift/add for that small scale numerator. This check covers arithmetic synthesis;
it is not a simulation of placed/routed BRAM primitives or the analog clock manager.

## Existing mesh target

The main target renders **3,442 vertices and 6,950 triangles at native 640×480**.
The onboard ADV7511 sends 640×480 at 60 Hz. Geometry, rendering, and scanout run
on the FPGA; no host sends animated vertices or pixels, and no DDR is required.

[JAX workload](cpu/workload.py) → StableHLO → generated RV32 program → VexRiscv
and **two 4×4 INT8 TPU cores** → [CPU HDMI driver](../../include/tiny3tpu_hdmi.h)
→ triangle rasterizer → double-buffered BRAM → HDMI.

JAX runs on the development computer during compilation and reference testing.
The FPGA executes the resulting freestanding program. Each frame computes
sine/cosine, constructs and quantizes the rotation matrix, and transforms the
resident mesh with `jax.lax.dot_general`. The workload-specific backend submits
431 paired launches to the two real TPU cores. Its 3×3 transform specialization
loads the shared matrix once, streams packed vertices, and reads INT32 results
directly; three INT8 products cannot overflow INT32. Other GEMM shapes use the
general backend. The first angle is checked against 10,326 exact JAX coordinates
on the board before submission. Those reference values are only assertions;
they never supply rendered geometry.

The CPU computes the next transform while the rasterizer draws the current
frame. The renderer tests two candidate pixels per cycle, overlaps depth reads
with pixel commits, and publishes completed images only at vertical blank.
All logic shares 25.2 MHz. HDMI refresh is 60 Hz and animation publishes at a
regular **30 fps** (every second refresh), following the preference for more
detail. Each rendered pixel stores a 6-bit material index. Area-weighted vertex
normals drive Gouraud interpolation and a 64-level gold palette, replacing the
old constant shade per triangle. Six compare/subtract stages quantize the
barycentric light numerator without a general hardware divider.

The original [jaxsim banana OBJ](https://github.com/SRA-VJTI/jaxsim/blob/c0a097bba1c6db10cac7b359fbac11cfedc48c6b/examples/sampledata/banana.obj)
contains 7,500 vertices and 15,000 triangles, counted directly from the pinned
source. The new mesh retains about 46% of its triangles, versus the previous
590-vertex / 1,181-triangle image. The larger mesh improves the outline; vertex
shading removes the conspicuous flat facets. The renderer still uses INT8
geometry, an orthographic projection, and average depth per triangle. It does
not implement jaxsim's complete floating-point soft rasterizer or antialiasing.

The complete CPU/dual-TPU rotation test sustained 30 fps: all 256 measured
publication intervals, including the wrap from phase 255 back to phase 0, were
840,000 cycles. The separate renderer sweep took
314,562–403,871 cycles per image (12.48–16.03 ms), leaving time for uploads in the
33.33 ms animation period. These are simulated times, not monitor latency.
Firmware uses 208,392 bytes of static RAM. Expanding on-chip CPU RAM to 256 KiB
leaves 49,656 bytes after reserving a 4 KiB stack. Runtime peak stack is not measured.

## Build and check

Use Python with JAX and NumPy (the local `.venv/bin/python` has both), plus the
RISC-V toolchain, Verilator/C++, Icarus Verilog, Yosys, nextpnr-xilinx, and openXC7.
Pillow is optional; tests always produce PPM captures.

```sh
.venv/bin/python hardware/kc705_hdmi/cpu/prepare.py \
  --out build-kc705-hdmi/smooth-firmware
python3 hardware/kc705_hdmi/tests/test_mmio.py \
  --out build-kc705-hdmi/smooth-mmio
.venv/bin/python hardware/kc705_hdmi/tests/test_cpu.py --full-rotation \
  --firmware build-kc705-hdmi/smooth-firmware \
  --out build-kc705-hdmi/smooth-full-cpu
.venv/bin/python hardware/kc705_hdmi/tests/test_rotation.py \
  --cpu-firmware build-kc705-hdmi/smooth-firmware \
  --out build-kc705-hdmi/smooth-rotation
python3 hardware/kc705_hdmi/tb/test_init.py
python3 hardware/kc705_hdmi/build.py bitstream --cpu \
  --firmware build-kc705-hdmi/smooth-firmware \
  --out build-kc705-hdmi/smooth-board
```

The full CPU test executes all 256 rotation phases and the wrap back to phase 0
with actual RV32 firmware, both TPU cores, MMIO, rasterization, and scanout. It
checks raw TPU results and uploaded vertices against JAX, measures all publication
intervals, checks the first 12 completed rasters and the wrapped phase 0 against
scalar edge equations, and decodes 16 full HDMI refreshes covering the first
eight animation phases. A separate renderer regression checks **78,643,200
pixels across all 256 angles** using JAX-derived input geometry. Firmware
preparation also checks all 2,643,456 generated native INT32 outputs against JAX.
MMIO tests cover upload order and bounds, the expanded 12-bit vertex addressing,
incomplete submissions, invalid addresses and strobes, response backpressure,
busy writes, and sticky buttons. Reports record source hashes and actual counts.

The smaller **407-triangle RTL-only** mode remains available without `--cpu` or
firmware. It uses one 4×4 TPU, rotation ROMs, and native 640×480 rendering:

```sh
python3 hardware/kc705_hdmi/tests/test.py
python3 hardware/kc705_hdmi/tests/test_rotation.py
python3 hardware/kc705_hdmi/build.py bitstream --out build-kc705-hdmi/standalone
```

CTest registers `kc705_hdmi_cpu` (including firmware preparation and the full CPU
rotation), `kc705_hdmi_mmio`, `kc705_hdmi_display`, `kc705_hdmi_rotation`, and
`kc705_hdmi_init`. The CPU test skips with code 77 if JAX/NumPy are unavailable.
The separate CPU renderer rotation command above checks every raster pixel.

`build.py --help` lists tool paths. The local Kintex-7 database is
`build-kc705-hdmi/chipdb/xc7k325tffg900-2.bin`. `synth`, `route`, and `bitstream`
each start from current sources. Export requires the route guard and compares
all configuration frames decoded from the resulting bitstream, excluding only
regenerated ECC bits. Source, asset, firmware, tool, and artifact hashes are
recorded; changed build inputs are rejected. The build command does not program
the board.

Synthesis uses 50 DSP48E1s, 276 RAMB36E1s, and 11 RAMB18E1s. Resource counts,
routing, and export results are recorded in the build manifests.
The routed internal timing model reports 63.75 MHz against the 25.2 MHz target;
the operating clock remains 25.2 MHz, and this does not qualify external HDMI I/O.
Small light-coefficient products use shift/add logic because the current timing
backend rejects the DSP register profiles otherwise selected for this operation.
The synthesis flow maps large memories to independent BRAMs and fabric selection
logic. Dedicated BRAM data cascades are disabled because the current nextpnr
placement repair can break previously placed cascade pairs.

The CPU controls transformed-vertex uploads and render submission through MMIO.
HDMI timing, scanout, vertical-blank publication, and ADV7511 I²C initialization
remain in RTL. This mesh target has no CPU register interface for transmitter
configuration, initialization recovery, or framebuffer writes; CPU pixel uploads
use the separate framebuffer target described above.

## Mesh and CPU interface

The high-detail [mesh](assets/mesh.json) is separate from the unchanged Chromatic
assets. It uses the pinned jaxsim banana OBJ and a 36×36×36 clustering grid,
centers the bounding box, and quantizes vertices to INT8 with maximum absolute
coordinate 110. Vertex normals are computed from the floating-point reduced
mesh before quantization. Equal INT8 positions are welded; 54 collapsed faces
and duplicate faces are removed, and unused vertices are eliminated. The final
mesh has 3,442 vertices and 6,950 nondegenerate triangles.

```sh
.venv/bin/python hardware/kc705_hdmi/tools/mesh_assets.py \
  --source build-kc705-hdmi/jaxsim-source/examples/sampledata/banana.obj --grid 36
```

The generator checks the source SHA-256. The face ROM stores three 12-bit vertex
indices and three 6-bit vertex shades in BRAM. Its capacity is 8,192 faces, and
projected-vertex RAM holds 4,096 entries. `assets/mesh_config.vh` records the
actual mesh counts, address widths, 256 KiB CPU RAM, and animation period.
The firmware and tests derive dimensions from these generated assets.

Registers are 32-bit, word-aligned, at base `0x40000000`. Only full-word writes
are supported; the 128 KiB aperture does not alias control registers into vertex RAM.

| Offset | Access | Meaning |
| --- | --- | --- |
| `0x00` | R | ID `0x48444d49` |
| `0x04` | R | Ready, rendering, display-valid bits 0–2 |
| `0x08` | W | Submit `0x80000000 \| phase` after all vertices |
| `0x0c` | R | Uploaded vertex count |
| `0x10` | R | Held controls |
| `0x14` | R/W1C | Sticky button presses |
| `0x18` | R | Last render cycles |
| `0x1c` | R | Published-frame count |
| `0x20` | R | Displayed phase |
| `0x24`, `0x28` | R | Vertex and triangle counts |
| `0x10000 + 4*i` | W | Vertex i: X bits 9:0, Y 19:10, Z 27:20 |

Projection is X = 320 + (Qx >> 6), Y = 280 − (Qy >> 6),
Z = 128 + (Qz >> 7). Out-of-bounds coordinates, unordered uploads, and writes
while busy are rejected. The old `0x400` and `0x1000` vertex apertures are retired. The CPU
checks the hardware vertex count before running to catch mismatched firmware.

## Connect and run

Connect KC705 power, USB-JTAG, and an HDMI monitor to connector P6. Load volatile
SRAM (configuration flash is not written):

```sh
openFPGALoader -b kc705 --ftdi-serial 210203A3CFBC --write-sram \
  build-kc705-hdmi/smooth-board/soc.bit
```

On startup the design waits 200 ms, selects I²C mux channel 5, waits for hot-plug,
configures the ADV7511, and checks its PLL lock. Video starts at a complete frame
boundary. Disconnecting/reconnecting HDMI reloads transmitter settings.

| Control | Action |
| --- | --- |
| Center button | Pause/resume |
| North button | Increase rotation speed |
| SW11 position 3, off → on | Decrease rotation speed |
| SW11 position 2 on / east button held | Backward/forward |
| SW11 position 4 | On: diagnostic bars; off: banana |
| CPU reset button | Reset CPU, renderer, HDMI initialization |

SW11 physical numbering is opposite to GPIO bit numbering: position 4 is
`GPIO_DIP_SW0`, position 3 is bit 1, and position 2 is bit 2. Leave position 2 off
for normal forward rotation. South and west buttons remain unused because of
openXC7 pin-feature mapping issues; the supported switches provide those controls
without changing the board's electrical standards.

| LED | Meaning |
| --- | --- |
| 0 | Pixel PLL locked |
| 1 | ADV7511 configured, hot-plug and transmitter lock confirmed |
| 2 | HDMI initialization exhausted retries, or CPU fault/nonzero exit |
| 3 | Completed image available |
| 4 | Rasterizer busy |
| 5 | Front framebuffer bank |
| 6 | Color bars selected |
| 7 | Published-frame counter bit 5 |

## Physical evidence and limits

The earlier 160×144 image had swapped Y/chroma bytes and green/purple bars. After
the byte-order fix was loaded, the user confirmed **“Bars correct and banana
yellow.”** The corrected mapping is preserved: board bus bits 7:0 carry Y and
15:8 carry alternating Cb/Cr, with Cb on the first active pixel. Fixed color-bar
words independently test this mapping. The FPGA sends limited-range BT.601
YCbCr 4:2:2 with averaged pair chroma, separate negative HS/VS, and external DE;
the ADV7511 converts to RGB HDMI. Audio and HDCP are disabled.

Load logs and image hashes are recorded separately under
`build-kc705-hdmi/hardware-validation/`. The retained 407-triangle CPU image is
`build-kc705-hdmi/cpu-board/soc.bit`; the new image has its own
`smooth-load-report.json`. Programmer success does not prove what appeared
on the monitor; physical visual confirmation is tracked independently.
The 6,950-triangle image was successfully loaded into volatile SRAM on
2026-10-11 at 14:47 UTC after checking 216 source/artifact hash entries. Its
SHA-256 is `a15dc7adc29f065cd6d2f67cf975accc07433d6c92fedfcd11e7a9ee32fc0098`;
the programmer reported `isc_done 1`, `init 1`, and `done 1`. Visual confirmation
of this specific image is pending. Flash was not written.
The earlier 1,181-triangle image and its successful load record remain at
`build-kc705-hdmi/detail1181-board/soc.bit` and `detail1181-load-report.json`.

Nextpnr checks modeled internal routes. This backend does not implement the
complete generated-clock/output-delay constraints needed to certify external
ADV7511 timing. The forwarded clock is inverted for nominal half-cycle capture
spacing; external setup/hold, PCB skew, and jitter remain unqualified. Neither
a 30 fps simulation nor the earlier visual confirmation measures monitor latency.

See [ADV7511 register provenance](ADV7511_REGISTERS.md),
[AMD KC705 UG810](https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content),
and [ADI KC705 constraints](https://github.com/analogdevicesinc/hdl/blob/hdl_2017_r1/projects/adv7511/kc705/system_constr.xdc).
