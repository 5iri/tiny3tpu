# MJX learning on the CPU/TPU/HDMI system

This implements the requested execution path:

```text
offline JAX/MJX -> StableHLO -> freestanding RISC-V firmware
                                   |
                       CPU runs one training tick
                                   |
                       compiler-emitted INT8 TPU call
                                   |
                       CPU finishes physics and learning
                                   |
                       CPU runs MJX kinematics + MuJoCo renderer
                                   |
                       back framebuffer -> vblank swap -> HDMI
```

`workload.py` calls **MuJoCo MJX-JAX 3.15.0's `mjx.step`**. It models a motorized,
contact-free hinge with a one-metre capsule, initially near the unstable upright
position. It is an upright balancing task, not swing-up. The physics is not a
handwritten pendulum equation. The static MJX model is specialized offline; its
configuration is also written to `model.xml` for inspection.

The initial learner is antithetic random-search policy optimization, not PPO or
an actor–critic. It starts with zero weights and keeps the simulator state,
random generator, returns, perturbations, update accumulators and float master
weights on the board. Every tick advances actual MJX physics and the learner's
state machine. One update uses four perturbation directions, two rollouts each,
and 128 steps per rollout. `make_learner()` provides a whole-update reference;
`make_tick()` exposes the same algorithm one physics step at a time so the CPU
can render between steps. No differentiation through the simulator is used.

The two policy features are sine of the hinge angle and one quarter of angular
velocity. Features and weights are explicitly clipped and quantized before the
INT8 product. Float master weights are updated from return differences; this is
not an implicit float-to-INT8 compiler transformation. The build uses the
compiler's `gemm_policy='tpu'` to exercise acceleration. Such a small product is
not expected to be faster than CPU arithmetic; no acceleration benefit is
claimed. All other work uses the board CPU, including software floating point.

The firmware renders the **current training trajectory**, including exploration,
every eight physics ticks. It executes upstream MuJoCo's `mjr_render` on the CPU
with a bounded TinyGL software OpenGL backend. Live geom transforms come from
compiled MJX `kinematics`; the earlier handwritten stick drawing is removed.
The CPU uploads the resulting RGB565 pixels to the double buffer: 320×240 for
the default VGA mode, or 480×270 with `--video-mode 720p`.
HDMI independently refreshes the last completed image at 60 Hz. Neither that
refresh rate nor image publication frequency is the simulation's real-time speed.

The [renderer port](render/README.md) describes the supported scene features,
static scene specialization, source provenance, reference-image checks and
memory requirements. It is a limited port for this small primitive scene;
textures, shadows, meshes and full OpenGL compatibility are not supplied.

## Reproduce

For the higher-resolution HDMI target:

```sh
# Live learning, actual MuJoCo renderer, 480x270 -> 1280x720 HDMI.
.venv-mjx/bin/python sidequests/mjx_rl/prepare.py --video-mode 720p --out build-mjx/720p-autonomous
python3 hardware/kc705_hdmi/build.py synth --cpu --framebuffer \
  --firmware build-mjx/720p-autonomous --out build-mjx/720p-board

# Bounded execution through the real CPU, TPUs and HDMI RTL.
.venv-mjx/bin/python sidequests/mjx_rl/render/verify_rtl.py build-mjx/720p-rtl --video-mode 720p
.venv-mjx/bin/python sidequests/mjx_rl/render/verify_native.py build-mjx/720p-native --video-mode 720p
```

The output is **1280×720 / 60 Hz**, with a 16:9 camera viewport. Rendering is
**480×270** (129,600 source pixels, up from 76,800), enlarged by 8/3 with exact
aspect preservation. This does not claim 921,600 independently rendered pixels
or 60 newly rendered frames per second. A native 720p renderer and its depth/color
buffers need a larger memory arrangement, such as the planned DDR3 path.

This configuration reserves 1216 KiB of CPU BRAM, including a 640 KiB renderer
arena and 16 KiB stack, plus two 259,200-byte display banks. Autonomous firmware
uses 1,205,920 static bytes, leaving 22,880 bytes after the reserved stack. The
CPU and video clock target is 74.25 MHz; synthesis and cycle simulation alone
do not qualify that operating frequency on the physical board.

The 720p build uses 432 RAMB36E1s, four RAMB18E1s and 42 DSP48E1s. The scanout
and coarse synthesis regressions each check 3,686,400 HDMI pixels, including
sync polarity, fractional scaling, blanking, MMIO rejection and vblank swaps.
The ADV7511 pin-level test checks the 720p aspect/VIC settings plus reconnect,
retry and stuck-bus recovery with the 74.25 MHz I²C divider. Four native image
comparisons against MuJoCo's standard OpenGL renderer also pass at 480×270.

`build-mjx/720p-verified/verification.json` records the final integrated run:
16 physics ticks, one policy update, three calls to upstream `mjr_render`,
194,400 framebuffer upload words and **4,608,000 exact HDMI pixel checks**.
All three CPU images equal native MuJoCo/TinyGL images pixel for pixel. The
latest decoded capture is `build-mjx/720p-verified/frame-2.png` (1280×720).
Publication intervals are 117,562,500 and 116,325,000 cycles, nominally 1.58
and 1.57 seconds at the requested 74.25 MHz; first publication takes
330,363,001 cycles. These are cycle estimates conditional on meeting that
clock, not measured physical frame rates. No 720p route or board load is claimed.

Use a separate environment so installing MuJoCo does not alter other demos:

```sh
uv venv .venv-mjx --python .venv/bin/python
uv pip install --python .venv-mjx/bin/python -r sidequests/mjx_rl/requirements.txt

# Repeated rendering, bounded memory and unsupported-feature rejection.
.venv-mjx/bin/python sidequests/mjx_rl/test_renderer_contract.py build-mjx/render-contract

# Full native learning checks, then a bounded CPU/TPU/MJX/framebuffer/HDMI test.
.venv-mjx/bin/python sidequests/mjx_rl/verify.py --out build-mjx/verified --rtl

# Autonomous firmware: zero initial weights; no verification or pretrained data.
.venv-mjx/bin/python sidequests/mjx_rl/prepare.py --out build-mjx/autonomous
python3 hardware/kc705_hdmi/build.py synth --cpu --framebuffer \
  --firmware build-mjx/autonomous --out build-mjx/board
```

The optional CMake cache setting `TINY3TPU_MJX_PYTHON` registers this check as
`mjx_rl_hdmi`. The RTL run requires Verilator, a RISC-V GCC toolchain and the
sibling `synapse32` UART source, like the existing SoC tests.

`prepare.py --horizon 6 --directions 1 --verify-ticks 16` builds a **test-only**
image. It checks all 20 returned float-state words on every tick against native
generated C, completes one small update, publishes three frames, and then keeps
scanout running. The default autonomous image has no expected-state table and
does not stop after those 16 ticks.

## Evidence and limits

`verify.py` writes `learning.json` and, with `--rtl`, `rtl/verification.json` plus
decoded HDMI PPM images. The checks establish:

- 64 independent one-step comparisons of generated physics against native
  MuJoCo; observed maximum absolute state error was `5.96e-8`.
- Native generated-C learning for seeds 1, 7 and 19: 100 updates / 102,400 physics
  steps each. A software QGEMM oracle supplies the TPU interface in this check.
  The trained policies are independently evaluated in JAX/MJX for 512 steps
  (10.24 simulated seconds) from held-out angles −0.25, −0.1, 0.1 and 0.25 radians.
  All twelve average returns exceeded 0.998; initial-policy returns ranged from
  approximately −0.185 to −0.142. Reward is cosine of angle minus velocity and
  action costs, so its per-step maximum is 1.
- A bounded integrated RTL run executes 16 actual training ticks, one weight
  update, 16 accelerator calls, and CPU framebuffer uploads. All 320 state words
  must match native C exactly. CPU uploads are compared with native execution
  of the same MuJoCo/TinyGL renderer; HDMI pixels match the actual uploads exactly.
  The test also observes three entries into upstream `mjr_render`. Both core launch signals fire; the tiny policy's
  second core has padded work, so this does not imply useful dual-core occupancy.

The MuJoCo renderer integration additionally passed 65 pose comparisons against
native MuJoCo (maximum absolute error `1.19e-7`), four image comparisons against
the installed OpenGL renderer, and a 64-frame persistent-allocation check.
The earlier VGA six-step-rollout RTL fixture captured three distinct live frames:
all CPU RGB565 uploads match host MuJoCo/TinyGL execution exactly, and
**1,536,000 HDMI pixels** match those uploads. Synthesis uses 332 RAMB36E1s,
4 RAMB18E1s and 42 DSP48E1s. Autonomous firmware allocates 969,200 bytes,
leaving 62,992 bytes after its 16 KiB stack reservation.

Measured publication intervals in this RTL fixture are 115,080,000 and
114,660,000 cycles: approximately **4.57 and 4.55 seconds** at the nominal
25.2 MHz clock, including eight training ticks and a render. Startup through the
first published image takes 328,404,001 cycles (about 13.03 seconds). These are
cycle-based estimates, not measurements from a physical board. The existing
software floating-point CPU is the main limitation for this rendering path.

Full 100-update learning convergence is verified in **native C**, not in a full
physical FPGA run. The bounded RTL check is an execution and transport proof,
not evidence of full-run FPGA convergence or training throughput. No board is
programmed by these scripts. Routed timing, external HDMI timing, physical
display operation, and long-run physical learning remain to be verified.

The default VGA MuJoCo renderer target uses 1 MiB of CPU BRAM and two 320×240 RGB565
BRAM framebuffers. A 16 KiB stack and 512 KiB renderer arena are included in
the CPU memory allocation. Working DDR3 is not needed for this proof. Larger models,
rollout storage and higher-resolution framebuffers can use DDR3 once the chosen
board has a verified controller and a non-overlapping memory map. This work does
not implement or qualify that DDR3 path. The present soft-float CPU remains a
performance constraint even with more memory.
