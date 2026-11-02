# MuJoCo rendering on the FPGA CPU

The firmware runs the real MuJoCo 3.15.0 **`mjr_render`** implementation. Its
OpenGL commands execute in TinyGL, a software rasterizer, on the same RISC-V
CPU that runs compiled MJX and the learner. No host supplies images or poses.

```text
compiled MJX training tick ↔ compiler-emitted TPU calls
        ↓ live qpos
compiled MJX kinematics → geom_xpos / geom_xmat
        ↓
MuJoCo mjr_render → TinyGL software rasterization
        ↓ RGB565 pixels, CPU RAM
CPU framebuffer upload → vblank swap → VGA or 720p HDMI
```

The renderer is ordinary C compiled for RV32IM, separate from the StableHLO
physics/training/kinematics graphs. TinyGL is the graphics backend, not a
replacement pendulum drawing. Upstream MuJoCo generates the primitive geometry,
applies the camera, sets materials and lights, and submits each frame.

## What is specialized

`export_scene.py` uses the installed MuJoCo `mjv_updateScene` offline to export
static geometry metadata, a fixed camera and headlight. It gives the pendulum a
blue material and adds a static pedestal with MuJoCo's `mjv_initGeom` API. These
are visualization settings, not changes to the simulated mass or dynamics.

Positions and rotations of model geometry are **not baked into playback**:
`pose.py` exports actual MJX `kinematics`, which the CPU executes on current qpos
before each frame. No sine/cosine pendulum drawing remains in the firmware.
The scene template retains initial transforms as metadata, but every model geom
transform is overwritten by the live MJX result before `mjr_render` runs.

This is a bounded port for the current single-hinge model. Opaque sphere,
capsule and box geometry, a fixed perspective camera, material lighting and
occlusion are supported. The exporter rejects other scene content. Textures,
meshes, skins, flexes, shadows, reflections, transparency, text overlays and a
windowing system are not implemented. Unsupported GL operations terminate the
program rather than fabricating an image. The adapter is not full OpenGL 1.5.

`mjr_makeContextTiny` creates the required built-in lists using upstream
MuJoCo tessellation. It replaces platform context/resource initialization;
**the upstream `render_gl3.c` containing `mjr_render` is unchanged**. The exact
vendored revisions, licenses and local changes are recorded in
`third_party/mujoco_renderer/` and `third_party/tinygl/`.

## Memory and execution

The default VGA target enlarges the unified CPU BRAM from 256 KiB to **1 MiB** and uses
two 320×240 RGB565 display banks. Firmware also keeps its CPU rendering buffer
and a bounded 512 KiB renderer arena in that 1 MiB. Every render checks that arena
usage stays constant; no allocation is allowed during frames. A 16 KiB stack is
reserved by the linker. Native tests use a larger arena because native pointers
and display-list entries are wider.

With `prepare.py --video-mode 720p`, MuJoCo renders a **480×270** widescreen
viewport and HDMI scans **1280×720 at 60 Hz**. The 8/3 nearest-neighbor enlargement
preserves aspect ratio. This profile uses 1216 KiB of CPU memory, a 640 KiB arena,
the same 16 KiB stack reservation, and two 259,200-byte display banks. The native
runner and image comparisons accept both resolutions. Rendering remains on the
actual MuJoCo/TinyGL path; the extra HDMI pixels are scaled source pixels.

The cross build links newlib's software math and minimal string routines. IEEE
libm entry points avoid desktop math-error logging; renderer errors use the
existing MMIO failure port. The port requires no OS or graphics accelerator.
This proof does not depend on DDR3 and does not qualify a DDR3 controller.

The CPU has no hardware floating-point unit. Primitive initialization and frame
rendering are consequently expensive. HDMI continues scanning out the latest
frame at 60 Hz; that is independent of simulation or rendering speed.

## Checks

```sh
# Compare the software port with the standard installed MuJoCo OpenGL renderer.
.venv-mjx/bin/python sidequests/mjx_rl/render/verify_native.py build-mjx/render-native

# Build firmware and execute the actual CPU/TPU/renderer/display RTL.
.venv-mjx/bin/python sidequests/mjx_rl/render/verify_rtl.py build-mjx/render-rtl

# Autonomous trainer; then synthesis (no board programming).
.venv-mjx/bin/python sidequests/mjx_rl/prepare.py --out build-mjx/render-autonomous
python3 hardware/kc705_hdmi/build.py synth --cpu --framebuffer \
  --firmware build-mjx/render-autonomous --out build-mjx/render-board

# Widescreen mode, including the complete execution test.
.venv-mjx/bin/python sidequests/mjx_rl/render/verify_rtl.py build-mjx/720p-rtl --video-mode 720p
.venv-mjx/bin/python sidequests/mjx_rl/render/verify_native.py build-mjx/720p-native --video-mode 720p
```

The native image check exercises four angles, compares silhouettes and color
against the installed MuJoCo renderer, and saves both images. Different pixel
coverage rules and RGB565 precision mean pixel identity is not expected.

The integrated test checks all 320 learning-state words over 16 ticks, one weight
update and 16 TPU calls. It observes execution entering `mjr_render` three times,
captures actual CPU uploads, compares them to host execution of the same software
renderer, and checks every pixel of captured HDMI frames exactly against those
uploads. Image publication must occur at vertical blank. It retains two whole
video periods per publication to keep trace size bounded while the CPU runs
continuously. This is digital RTL evidence, not physical FPGA execution or a
claim of real-time rendering.
