# KC705 Rocket + tiny3tpu

Experimental target, stopped at the user's request on 2026-09-30. The active
cloth demo uses VexRiscv at 100 MHz. Rocket passed RTL tests but did **not** boot
the application successfully on the physical board; there is no live Rocket FPS
result. Keep this target separate from the working VexRiscv image.

This target uses pinned Rocket RV64GC with FP32/FP64 hardware arithmetic,
16 KiB instruction/data caches, existing int8 TPU, UART, and 64 KiB boot RAM.
All application state and computation remain on the board. The StableHLO
compiler emits portable C; the board toolchain selects RV64GC/lp64d. The
`kc705-rocket` compiler target keeps the old RV32 software-float cost model out
of automatic affine placement. Exact int8 GEMM still goes through the TPU.

## Implementation

- `rocket_wb.sv` ties off unused upstream interfaces and instantiates separate
  adapters for cached memory and uncached MMIO.
- `axi64_to_wb32.sv` accepts aligned FIXED/INCR bursts and independent AW/W
  arrival, preserves IDs and backpressure, and propagates errors. Narrow reads
  access only their addressed 32-bit word; unsupported size/alignment/burst,
  locked transactions, and invalid write strobes return SLVERR.
- `rocket_tpu_soc.sv` arbitrates the two adapters at word boundaries and retains
  the UART/TPU/report/timer map. The external reset ROM at `0x10000000` jumps to
  RAM at `0x80000000`. `start.S` enables floating-point register state and installs
  a diagnostic trap handler before entering C.
- `kc705_rocket_noddr_top.sv` has a build-selected PLL divisor. The bring-up
  configuration targets 25 MHz; `--clock-mhz` changes the PLL, timing constraints,
  firmware UART divisor and viewer cycle conversion together. DDR is absent.

The upstream FPU uses DSP input-register modes unsupported by the qualified
local router. Synthesis therefore leaves Rocket's pipeline registers in fabric
and uses combinational DSP multipliers. TPU DSP packing retains its checked
PREG MAC mode. This preserves architectural pipeline latency and retains timing
checks; unsupported DSP profiles and timing failures still reject the image.

## Validation and reproduction

```sh
# Native compiler and full Rocket/TPU RTL workloads.
/tmp/tiny3tpu-banana-venv/bin/python tests/test_stablehlo_compiler.py
/tmp/tiny3tpu-banana-venv/bin/python tests/test_stablehlo_soc.py \
  --cpu rocket --profile --out build-rocket/smoke
/tmp/tiny3tpu-banana-venv/bin/python tests/test_rocket_fpu.py --out build-rocket/fpu
/tmp/tiny3tpu-banana-venv/bin/python tests/test_stablehlo_soc.py \
  --cpu rocket --profile --steps 8 --out build-rocket/cloth-fused \
  --artifact build-cloth/stablehlo/cloth.mlirbc --input build-cloth/stablehlo/input.npy

# Build a candidate; does not program the board.
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/build_compiled_board.py \
  --cpu rocket --clock-mhz 25 --out build-cloth/rocket-board-25
/tmp/tiny3tpu-banana-venv/bin/python sidequests/cloth/compiled_uart_sim.py \
  --board build-cloth/rocket-board-25 --out build-rocket/uart-25
```

The bridge regression is available as CTest `rocket_axi_bridge`. FPU vectors
check exact finite, signed-zero, and infinity bits; NaN payload/sign are compared
by class. The generated program tests compare every output word to independent
native execution of the generated C, not long-run JAX trajectories.

Initial RTL measurements at an assumed 100 MHz:

| Program | Cycles | Time |
| --- | ---: | ---: |
| VexRiscv, first unfused cloth step | 11,121,986 | 111.220 ms |
| Rocket, first unfused cloth step | 582,771 | 5.828 ms |
| Rocket, eight unfused steps | 4,688,415 | 46.884 ms |
| Rocket, eight fused steps | 3,923,626 | 39.236 ms |

The eight-step runs keep state on board between calls and match all 180 final
float32 words. The generic smoke test also verifies physical TPU RTL calls.
640 FP32/FP64 arithmetic/square-root vectors passed. These are RTL results;
the production firmware UART test also matched all 180 state words and 84
transformed coordinates per request. Physical programming and live FPS must be
reported separately after a valid route, bitstream roundtrip, and board checks. The openXC7 timing model has the
same BRAM/clock-skew/hold coverage limitations documented for the VexRiscv image.

The initial 100 MHz route failed at 35.13 MHz. Its critical path runs from an
instruction-cache tag hit through instruction/decode logic to a register enable
(4.2 ns logic and 24.3 ns routing in this placement). The
bring-up clock is therefore lower; the nominal 100 MHz times above are cycle
comparisons, not a demonstrated clock rate for this implementation.

## Physical attempt

`build-cloth/rocket-board-25` passed the 25 MHz route check (reported limit
37.49 MHz) and an exact bitstream frame roundtrip across 27,850 frames. SRAM
programming reported DONE, but neither the startup UART capture nor requests
received any bytes. The user observed LED 0 locked and LED 7 blinking, with no
fault/exit indication. A two-cycle reset also passes the production RTL test,
and the boot RAM's defined words match the firmware through the routed FASM
mapping. These checks narrow the failure but do not identify its cause.

A diagnostic build using `--no-lutram` was stopped before completion. It has
not established whether distributed RAM mapping caused the physical failure.
The verified `build-cloth/optimized-board` VexRiscv image is the restore target.
