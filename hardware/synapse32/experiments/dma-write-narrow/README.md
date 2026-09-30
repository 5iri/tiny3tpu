# Bounded DMA write burst byte count

This opt-in experiment narrows `tr_word_count_reg/next` to seven bits under
the current 32-bit, aligned, 16-bit descriptor-length, 64-byte burst profile.
Other profiles retain `LEN_WIDTH`. Beat counters retain their original width
and zero-length underflow semantics. No pipeline stage or firmware change is
introduced; the original third-party RTL remains untouched.

`prove.py` checks the actual burst-selection source for every 16-bit remaining
length and 32-bit address, including zero, unaligned and page-boundary values.
The result is always 0..64. The byte-count register starts at zero, and its
other assignment holds its previous value. Full-module Yosys sequential
equivalence proves all 2,301 comparison points. Evidence and exact input hashes:
`build-dma-write-narrow-proved/results.json`.

Validation uses `--dma-write-narrow` in the DMA experiment driver:

- 27 DMA/TPU cases: 3,693 read beats, 3,685 write beats, 16,345 cycles.
- Smoke: 106,588 instructions / 142,895 enabled CPU edges, 789,205 system cycles.
- 45 shapes: 1,659,843 instructions / 2,084,686 enabled CPU edges,
  11,544,608 system cycles, 137,970 beats and 9,874 bursts in each direction.
- Complete PROFILE, METRICS and DMA records exactly match the selected
  atomic-word/UART/boot-prefix baseline. Comparison hashes are in
  `build-dma-write-narrow-proved/throughput-comparison.json`.
- Synthesis: 648 CARRY4, 6,508 LUT6, 7,415 FDRE, 6,366 FDCE, 36 DSP48E1,
  16 RAMB36E1. Relative to baseline: five fewer carry cells, 72 more LUT6,
  four fewer FDRE. The byte-count register itself is optimized away;
  narrowing is useful for the combinational consumers.

Routes: `build-ddr-seeds-write-narrow-graph`. All timing results require
expanded graph analysis; native MHz reports omit paths. No physical 100 MHz
closure or default promotion is implied.

Expanded diagnostic maxima (PCOUT/carry = 0/0, 1/0, 0/0.1 ns): seed 4 is
15.180 / 15.180 / 15.280 ns; seed 8 is 14.282 / 14.282 / 15.382 ns.
Neither improves the retained baseline, so this width-only version is not
selected. These substitutions are sensitivity probes, not validated delays.
Hash checks: `build-dma-write-narrow-proved/route-integrity.json`.
