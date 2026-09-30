# Factored DMA read burst capacity

This applies the [seven-bit burst/page capacity](../dma-write-limit/README.md)
to the DMA read engine, on top of the proved read-completion comparison.
Only the selected profile changes; other profiles keep their original burst
logic and width. Address/length state updates and wrapping ARLEN semantics,
including zero-length behavior, are preserved.

The actual original burst selection and factored expression are symbolically
equal for all 16-bit lengths and 32-bit addresses. Whole-module sequential
equivalence proves all 1,583 comparison points. Proof and exact source hashes:
`build-dma-read-limit-proved/results.json`. The driver checks the read-comparison
parent proof before applying this overlay with `--dma-read-limit`.

Paired with `--dma-write-limit`, the 27-case DMA/TPU suite passes in 16,345
cycles, and complete smoke/45-shape PROFILE, METRICS and DMA records exactly
match the previous selected baseline. The full workload remains 11,544,608
system cycles and 0.796208 IPC (1,659,843 / 2,084,686). Evidence:
`build-dma-read-limit-proved/throughput-comparison.json`.

Combined synthesis uses 627 CARRY4, 6,364 LUT6, 7,411 FDRE, 6,366 FDCE,
36 DSP48E1 and 16 RAMB36E1. Relative to the previous selected baseline this
removes 26 carry cells, 72 LUT6 and eight FDRE. Firmware and constraints are
byte identical. Evidence: `build-dma-read-limit-proved/synthesis-comparison.json`.

Routes are in `build-ddr-seeds-burst-limit-graph`. Timing-model coverage remains
incomplete; no native report or symbolic sensitivity probe establishes
physical 100 MHz closure.

| Seed | Zero substitutions | PCOUT 1 ns | Carry 0.1 ns |
| --- | ---: | ---: | ---: |
| 4 | 12.831 ns | 12.831 ns | 13.031 ns |
| 8 | 12.705 ns | 13.020 ns | 13.605 ns |

Seed 4 is selected across these diagnostic probes. The global endpoint moves
to CPU `exception_tval_q[6]`; its path is retained in
`build-ddr-burst-limit4-timing-sensitivity/critical-trace.json`. Seed 8 is
limited by the multiplier result register, including the modeled DSP cascade.
