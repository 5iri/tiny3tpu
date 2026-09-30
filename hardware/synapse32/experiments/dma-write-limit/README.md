# Factored DMA write burst capacity

This opt-in experiment replaces the current profile's wide page-crossing
arithmetic with a seven-bit capacity. In the final 64-byte block of a 4 KiB
page, capacity is `64 - address[5:0]`; elsewhere it is
`64 - address[1:0]`. The selected byte count is the smaller of capacity and
remaining length. Other profiles retain the original burst-selection logic
and byte-count width. Wrapping beat counters and all state transitions are
unchanged, with no added cycle or firmware change.

`prove.py` proves the capacity expression equals the actual original
burst-selection logic for all 16-bit remaining lengths and 32-bit addresses,
including zero, unaligned and boundary inputs. Full-module Yosys sequential
equivalence proves all 2,301 comparison points. Evidence and input hashes:
`build-dma-write-limit-proved/results.json`.

The DMA driver selects this generated RTL explicitly with `--dma-write-limit`
and checks its proof hashes. It is separate from the earlier last-cycle,
direct-terminal and width-only experiments. Original third-party RTL is not
modified.

The 27-case DMA/TPU unit suite passes with 16,345 cycles. Smoke and all 45 GEMM
shapes reproduce every PROFILE, METRICS and DMA field exactly:
`build-dma-write-limit-proved/throughput-comparison.json`. The full workload
remains 1,659,843 instructions / 2,084,686 enabled CPU edges = 0.796208 IPC,
11,544,608 system cycles, 137,970 beats and 9,874 bursts in each direction.

Synthesis uses 639 CARRY4, 6,361 LUT6, 7,415 FDRE, 6,366 FDCE, 36 DSP48E1,
and 16 RAMB36E1: 14 fewer carry cells, 75 fewer LUT6 and four fewer FDRE than
the previous selected baseline. Firmware and constraints remain byte exact.

Expanded timing probes (PCOUT/carry = 0/0, 1/0, 0/0.1 ns):

| Seed | Zero substitutions | PCOUT 1 ns | Carry 0.1 ns |
| --- | ---: | ---: | ---: |
| 4 | 13.378 ns | 13.378 ns | 14.308 ns |
| 8 | 14.032 ns | 14.032 ns | 15.162 ns |

Seed 4 improves both comparisons against the previous 13.961/14.661 ns
candidate. The seed-8 global endpoint is DMA **read** address bit 29, motivating
the paired [read capacity experiment](../dma-read-limit/README.md).
Route/hash evidence: `build-dma-write-limit-proved/route-integrity.json`.
Native MHz and symbolic probes do not establish physical full-SoC Fmax.
