# On-board cloth simulation

The current live demo uses the generic StableHLO compiler; see **Physical
compiler-generated demo** below. The initial handwritten port remains available
for comparison in `live_firmware.c` and `build-cloth/board`.

In the initial handwritten port, the KC705 RISC-V CPU runs the upstream jaxsim dflex spring, Neo-Hookean triangle,
dihedral bending and semi-implicit Euler equations in software float32. Both physical
int8 TPU cores transform the evolving, quantized geometry. The host receives only
camera-space geometry, checks UART checksums and rasterizes pixels with Pillow.
The live process imports no JAX and sends no positions, forces or velocities.

The mesh uses 6 × 3 cells (28 cloth vertices and two spring anchors), preserving
2 × 1 metre dimensions. Integration uses 1/7680 second substeps. This is an adapted
small mesh, not the original 20 × 10 resolution. It is not a JAX runtime on the FPGA:
the JAX model's operations were ported to freestanding C and execute on its CPU.

That port's CPU square roots use Newton iteration; bending acos uses a polynomial approximation.
Native C versus JAX maximum coordinate discrepancy is about 18 micrometres at one
simulated second and 7.3 centimetres at 1.5 seconds. The longer-run upstream JAX
reference becomes nonfinite in a ten-second check. Playback resets after the
example's original 1.5-second interval. Camera inputs use 0.125 metre quantization;
int32 accumulators preserve the TPU matrix product. Performance is measured from
completed physical board frames, and simulated time is displayed separately.

## Reproduce

Use the existing banana venv and upstream checkout, pinned at
`c0a097bba1c6db10cac7b359fbac11cfedc48c6b`:

```sh
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/export.py /tmp/tiny3tpu-jaxsim-banana
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/validate.py /tmp/tiny3tpu-jaxsim-banana
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/prepare_test.py
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/firmware_sim.py --live --vertices build-cloth --fixture build-cloth --out build-cloth/rtl
.venv-ddr-compat/bin/python tools/kc705_open_build.py route --cpu vexriscv-lite --synapse32-dir ../synapse32 --no-ddr --firmware-source sidequests/cloth/live_firmware.c --firmware-include build-cloth --build-dir build-cloth/board --chipdb /tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin --nextpnr build-banana/nextpnr-preg-grade2/nextpnr-xilinx --seed 4
/tmp/tiny3tpu-banana-venv/bin/python tools/kc705_export_bitstream.py --build-dir build-cloth/board --db-root build-banana/nextpnr-source/xilinx/external/prjxray-db/kintex7
openFPGALoader -b kc705 --ftdi-serial 210203A3CFBC --write-sram build-cloth/board/soc.bit
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/live.py
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/window.py --title 'KC705 — On-board Cloth' --heading 'KC705 / CLOTH' --scope 'RISC-V cloth physics + physical TPU transforms · host pixels only · no DDR'
```

Stop the prior live UART process before programming and starting this demo.
The double-pendulum source and its bitstream remain available in `sidequests/physics`
and `build-physics/board`. Frame metrics, image and report are in `build-cloth/live`.

## Compiler demonstration

The newer complete-step path is `compile_program.py /path/to/jaxsim
--affine-offload`. It exports portable StableHLO and uses the generic
[system compiler](../../docs_stablehlo.md). `program_check.c` provides an explicit
native reference callback; `tests/test_stablehlo_soc.py` can execute the same
artifact on actual CPU/TPU RTL. This path has no handwritten cloth physics in
the generated program. The physical deployment and viewer are described below.
See the compiler guide for current precision and performance limits.

### Physical compiler-generated demo

`compiled_live_firmware.c` now wraps the generated `t3p_run` program in a resident
state and UART loop. It contains no handwritten cloth force/integration equations.
The CPU executes generated floating-point operations and the physical TPU executes
profitable compiler affine partitions, as well as camera transforms. The display process
imports no JAX and sends only step/reset commands. It receives camera coordinates
for host projection, shading and pixels. A diagnostic flag additionally returns
the full state for testing; the normal viewer does not request it.

After the StableHLO export above:

```sh
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/build_compiled_board.py --out build-cloth/optimized-board --no-fusion
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/start_compiled.py --board build-cloth/optimized-board
```

The builder compiles the existing portable artifact and replaces only verified
boot RAM initialization bits in the
retained 100 MHz route. Both complete 64 KiB reconstruction and bitstream frame
roundtrip checks must pass. The linker reserves at least 4 KiB for the stack.

Physical checks on 2026-09-30 matched all 180 float32 state words bit-for-bit against
native compiled C, and all 84 camera coordinates, over one-step, two-step and reset
requests. The initial forced-offload build used two physics TPU calls per substep
and took 311–329 ms, plus about 20.8 ms for generic camera QGEMM.

The optimized VexRiscv build uses the packed generic driver and automatic affine placement.
Its compiler report rejects the affine physics partition as unprofitable, keeping
physics on the board CPU and camera transforms on the physical TPU. First-substep
physical time is about 111 ms, with 5.3 ms for camera transforms. All diagnostic
state/coordinate words again matched exactly. The native window displays zero
physics TPU calls accurately; there is still no host physics or JAX runtime.

Fusion and static index views are generic compiler features. They reduce this
CPU program's workspace from 10,088 to 8,244 bytes, but the one-step RTL benchmark
took 116.4 ms with them versus 111.2 ms without. The VexRiscv application builds
with `--no-fusion`; no cloth-specific rule exists in the compiler. To force affine
offload for comparisons, pass `--affine-policy force` to the board builder.
The start script validates the image manifest, stops only identified cloth
processes, programs SRAM, runs the diagnostic, and launches a display-only viewer.

Each substep advances only 1/7680 simulated second: display FPS is not real-time
physics throughput. The native reference runs only in the diagnostic checker and
does not drive the viewer. These checks do not remove the longer-run numerical
differences from JAX described in the compiler guide.

The older v1 accelerator-island demonstration below remains available separately.

Run `compiler_demo.py /tmp/tiny3tpu-jaxsim-banana` after `lower_forces.py` and building
`build-cloth/compiler/tiny3tpu-compile` and `tiny3tpu-run`. The demonstration writes
StableHLO for the full JAX step and records its host CPU JIT timing. The existing
TPU exporter rejects the full float32 graph; this is an explicit failure, not
CPU fallback disguised as TPU compilation.

`tools/jax_affine_lowering.py` proves affine dependence for a bounded JAX arithmetic
subset, extracts a row-independent matrix, checks its coefficient representation,
and exports QGEMM through the existing JAX exporter. Signed wider integer inputs
are split into low/high base-256 digits and outputs reconstructed exactly.
This currently compiles the cloth's two linear FEM force islands, not its entire
force calculation. Both compiled 1,440-byte `.t3m` artifacts match JAX through the
C runtime and actual TPU RTL simulation. Process wall times include startup and
are not hardware throughput measurements. This demonstration has not replaced
the live board firmware's physics implementation or improved its FPS yet.
