# Banana rendering sidequest

Adaptation of SRA-VJTI/jaxsim's [`softras_simple_render.py`](https://github.com/SRA-VJTI/jaxsim/blob/c0a097bba1c6db10cac7b359fbac11cfedc48c6b/examples/softras_simple_render.py),
pinned to commit `c0a097bba1c6db10cac7b359fbac11cfedc48c6b`.

The first stage renders a rotating banana at 64×64. Camera transforms execute
through the existing JAX exporter, compiler, C runtime and Verilated TPU
AXI-Stream mailbox. Every integer output is checked against JAX before it is
used for rendering. Lighting, perspective division and SoftRas run on the host.
This is forward rendering only; gradients and rasterization have not been
ported to the FPGA. The comparison uses the same reduced mesh on both paths.

## Run

Requires Python with the packages below, CMake, a C/C++ compiler, and Verilator.
Use a separate environment and build directory:

```sh
python3 -m venv build-banana/venv
build-banana/venv/bin/pip install -r sidequests/banana/requirements.txt
git clone https://github.com/SRA-VJTI/jaxsim.git build-banana/jaxsim
git -C build-banana/jaxsim checkout c0a097bba1c6db10cac7b359fbac11cfedc48c6b
cmake -S . -B build-banana -DPython3_EXECUTABLE="$PWD/build-banana/venv/bin/python"
cmake --build build-banana --target tiny3tpu-compile -j 4
ctest --test-dir build-banana -R '^tiny3tpu_axis_mailbox_rtl$' --output-on-failure
build-banana/venv/bin/python sidequests/banana/render.py --jaxsim build-banana/jaxsim
```

Outputs in `build-banana/render`:

- `jax-reference.gif`: floating-point camera transforms using upstream JAX code.
- `rtl-transform.gif`: int8 transforms run through actual TPU RTL simulation.
- `comparison.png`: reference, RTL, and amplified difference, left to right.
- `report.json`: mesh size, batch count, camera/image errors, and host wall times.
- `frame-NNN/transform.json` and `.t3m`: exported and compiled camera models.
- `banana_fixture.h`: first 32 vertices, transform weights/bias, model and expected results.
- `viewer.html`: animated comparison; open it in a browser.

`--backend jax` runs the quantized version without requiring compiler/RTL tools.
`--frames`, `--size`, and `--cells` adjust the animation, resolution and mesh detail.
Increasing these can substantially increase host rasterizer memory use.

Optional enlarged MP4, then open the viewer:

```sh
ffmpeg -y -stream_loop 3 -i build-banana/render/rtl-transform.gif \
  -vf scale=512:512:flags=neighbor -c:v libx264 -pix_fmt yuv420p \
  -movflags +faststart build-banana/render/banana-sim.mp4
open build-banana/render/viewer.html
```

## No-DDR firmware simulation

After rendering with `--backend rtl`, the generated fixture can also run on the
real VexRiscv CPU RTL with 64 KiB boot RAM and the TPU mailbox:

```sh
build-banana/venv/bin/python sidequests/banana/firmware_sim.py \
  --synapse32-dir ../synapse32
```

This additionally requires the RV32-capable `riscv64-unknown-elf` toolchain and
the adjacent Synapse32 checkout for UART RTL, matching the existing board flow.
It emits `build-banana/firmware/firmware.elf` and `firmware.hex`, compiles the
CPU/TPU RTL and checks all 96 output coordinates. Any external-memory request
fails the test. The fixture calls the C GEMM backend directly and adds the
camera translation bias on the CPU. The complete JAX model/runtime path is
checked by the host-driven RTL animation above.

This script does not synthesize or program the board. The firmware checks one
camera batch; the animation checks every vertex at every angle.

## Live board renderer

`prepare_live.py` emits the resident mesh for `live_firmware.c`. The firmware
accepts a camera matrix over UART and returns all 204 transformed vertices.
`live.py` checks every coordinate before host JAX rasterization; `window.py`
opens a native window with the image and measured FPS.

After programming the matching no-DDR live image:

```sh
build-banana/venv/bin/python sidequests/banana/live.py --jaxsim build-banana/jaxsim
# In another terminal (Python must include Tk):
build-banana/venv/bin/python sidequests/banana/window.py
```

UART reads wait indefinitely. While waiting, the window retains the last
verified frame, shows “Waiting for UART”, and hides FPS once the frame is stale.
The dashboard is also available at `http://127.0.0.1:8765`.

The first physical image intermittently lost UART request bytes. Supplying one
missing byte made a stalled request complete immediately. The SoC now includes
a two-register synchronizer between the external RX pin and the UART receiver.
After that change, over 100 consecutive physical frames passed exact coordinate
checks at about 1.58 FPS (including the 250 ms request pause). This strongly
implicates the previously unsynchronized input; metastability was not measured
directly. Evidence is saved in `build-banana/live/uart-investigation.json`.

The live protocol regression runs ten consecutive requests through the real
CPU, UART, and TPU RTL, checking every returned coordinate and checksum:

```sh
build-banana/venv/bin/python sidequests/banana/prepare_live.py
build-banana/venv/bin/python sidequests/banana/firmware_sim.py --live \
  --out build-banana/live-sim
```

## Representation and initial result

The original mesh has 7,500 vertices and 15,000 triangles. Vertex clustering
with eight cells per axis produces 204 vertices and 407 triangles. World
coordinates use an int8 scale chosen to fit ±110; rotation coefficients use
±127. A 32×3 by 3×3 GEMM produces int32 coordinates, with int32 translation
bias. Perspective division remains floating-point on the host.

The mesh representation needs 3,054 bytes with uint16 indices; a 64×64 RGB8
frame needs 12,288 bytes. No large face-by-pixel tensor is stored on the FPGA.
The current host SoftRas implementation does allocate such tensors.

The initial 12-angle run checked 84 RTL batches with exact integer agreement.
Maximum camera-coordinate error against float JAX was about 0.00536 world
units. Mean absolute RGB difference was at most 0.120 on a 0–255 scale, averaged
across the whole frame including the background. This measures quantization
error on the reduced mesh, not fidelity to the original high-resolution mesh.

The first no-DDR CPU/TPU firmware simulation checked all 96 coordinates and
exited successfully after 3,137,984 system cycles with no external-memory
accesses. That count includes startup and firmware checking; it is not an
isolated GEMM benchmark. The firmware image used 3,392 bytes of text/constants
and 384 bytes of BSS, plus stack.

GIF playback is four frames per second. Process startup, compilation and
simulation wall times are not physical FPGA throughput measurements.
The small camera GEMM is a correctness demo, not an established speedup.
