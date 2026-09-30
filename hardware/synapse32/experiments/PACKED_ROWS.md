# Packed operand rows

The AXI wrapper now accepts four operand bytes per addressed row write, using
the existing two-word stream command format. A two-core tile load needs **16
operand commands plus START**, replacing **192 operand commands plus START**.
The operation uses ordinary RV32IM loads, shifts and stores. Result collection,
per-command response checking, timeout handling and DMA ownership stay intact.

The aperture is documented in [docs_axi_registers.md](../../../docs_axi_registers.md).
It serializes four scratchpad stores and returns B after the final store. It is
not yet a tile queue, double buffer, or direct tensor stream into the PEs.

## Measured behavior

| Full-system workload | Default system cycles | Packed system cycles | Default IPC | Packed IPC |
|---|---:|---:|---:|---:|
| Smoke, 35 results | 1,185,342 | 1,030,141 | 0.775113 | 0.771373 |
| Stress, 162 results | 2,189,877 | 1,705,916 | 0.756835 | 0.746103 |

Cycles fall by 13.1% and 22.1%. DMA beats per direction fall from 4,506 to 1,690
in smoke and from 15,102 to 6,654 in stress. The packed firmware stays **opt-in**
because both aggregate IPC values are below the user's existing floor. The
default firmware retains its exact prior instruction profiles, trace hashes,
DMA counts and system cycles with the extended RTL.

The dense 8×16×8 GEMM call itself improves **both** time and IPC:

| GEMM-scoped metric | Default | Packed |
|---|---:|---:|
| System cycles | 419,050 | 253,039 |
| Instructions / enabled CPU edges | 59,823 / 73,773 | 38,001 / 46,512 |
| CPU IPC | 0.810906 | 0.817015 |
| Average array core-busy time | 0.03245% | 0.05375% |
| Useful MAC / available PE-cycle capacity | 0.007636% | 0.012646% |

That is 39.6% fewer cycles and 65.6% greater useful PE utilization for this call.
Utilization remains very low: software orchestration, result-command transport
and the original short-tile schedule still dominate. These are behavioral-memory
measurements, not physical DDR3 throughput or contention measurements. The
aggregate and per-GEMM IPC metrics cover different instruction mixes and windows;
the dense improvement does not establish an IPC improvement on every shape.

| GEMM shape | Cycle reduction | Default call IPC | Packed call IPC |
|---|---:|---:|---:|
| 1×1×1 | 61.2% | 0.743355 | 0.680369 |
| 4×8×4 | 36.9% | 0.797781 | 0.796620 |
| 7×13×9 | 45.7% | 0.799469 | 0.797907 |
| 8×16×8 | 39.6% | 0.810906 | 0.817015 |
| 3×5×6 | 43.9% | 0.778329 | 0.761591 |

## Validation and reproduction

- AXI regression: 832 signed matrix cells, all 16 byte-strobe combinations,
  independent AW/W ordering, stalled B, invalid/unaligned addresses, busy-write
  rejection, reset during each serialized store boundary, and legacy writes.
- Stream bridge: 29 responses, malformed frames, independent channel stalls,
  back-to-back beats and eight active-phase resets.
- Open DMA: all 27 cases, including AXI and command errors, descriptor bounds,
  final-write completion and coordinated reset.
- Actual RV32IM CPU + DMA + TPU: all 35 smoke and 162 stress results for both
  default and opt-in firmware. Observation-only utilization rebuilds check exact
  firmware bytes and original profiles.

```sh
python3 hardware/synapse32/experiments/dma/run.py system \
  --out build-packed-new --cpu-overlay-dir build-ddr-divider-payload/overlay \
  --system-mul --bus-payload --uart-control --dram-command-buffer \
  --dram-write-buffer --packed-rows
```

Use `stress` with a different output directory for the five-shape suite; omit
`--packed-rows` for the preserved default firmware. The equivalent compiler
define is `TINY3TPU_DMA_PACKED_ROWS`. The runner applies the same setting in
simulation and board compilation and rejects mismatched validation settings.
It now hashes the accelerator RTL as well as DMA and CPU sources before board
synthesis, preventing reuse of a validation result after accelerator edits.

Evidence: `build-ddr-packed-row/comparison.json`,
`build-ddr-dma-packed-default[-stress]/system/results.json`,
`build-ddr-dma-packed-optin[-stress]/system/results.json`, and
`build-ddr-utilization-packed-optin-{smoke,stress}/results.json`.

Board synthesis passes. Seed-4 routing reaches **102.51 MHz CPU / 81.57 MHz
system**, with system-to-CPU 8.62 ns and CPU-to-system 10.13 ns. The full 100 MHz
target still fails, and the existing unsupported I/O-bank constraint warning
remains. No hardware signoff or FPGA programming has occurred. Evidence is in
`build-ddr-dma-packed-optin/board/route-manifest.json`.

## Broader sweep

The later [45-shape sweep](GEMM_SWEEP.md) reports pooled GEMM IPC of 0.812468
legacy versus 0.820446 packed, and 42.86% fewer GEMM system cycles. It also lists
all per-shape regressions and the lower equal-shape mean; the five-shape and
full-program figures above are retained with their original measurement scope.
