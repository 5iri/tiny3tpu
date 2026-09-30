# Narrow TPU phase counters — current timing front-runner

The wrapper used signed 32-bit integers for feed/flush counters. Their reachable
ranges in the current N=4 arrays are 0..6 and 0..7. The opt-in `--tpu-counters`
uses parameter-derived unsigned widths, reducing both counters to three bits.
No FSM state, array clock, launch, MAC, load or result cycle is added or removed.

Compositional temporal induction passes for N=4. Both original and candidate
wrappers receive shared arbitrary array results. All wrapper state, array feed
inputs, clear, busy/done and read outputs are equal every cycle, with explicit
counter-range invariants. The systolic array RTL is unchanged; equal array inputs
and reset/clear preserve its behavior. The initial full-array proof was stopped
because it spent time on unchanged multipliers; it is not claimed as a pass.
Proof evidence: `build-tpu-counters-n4-compositional/results.json`.

Full-system smoke and all 45 GEMM shapes (3,022 checked results) retain exact
PROFILE, METRICS and DMA records. Full diagnostic time remains 11,544,608 system
cycles; no CPU IPC or useful-work/cycle regression. Evidence:
`build-ddr-dma-tpu-counters/system/results.json`,
`build-ddr-gemm-tpu-counters/system/results.json`.

Synthesis passes. Compared with retained hardware, it removes 116 flip-flops and
102 CARRY4 cells; LUT6 count falls from 6,519 to 6,166. Initial routed results:

| Seed | Baseline system / CPU MHz | Candidate system / CPU MHz |
|---|---:|---:|
| 4 | 81.57 / 102.51 | 85.82 / 95.19 |
| 7 | 81.14 / 102.43 | 81.22 / 89.49 |

The system-clock gain is promising, but neither route closes 100 MHz. All eight baseline seeds are now complete; see the comparison below. The candidate is not promoted as a
timing-clean board design. The unsupported I/O-bank constraint and physical DDR
signoff limitations remain. No timing exceptions are used.

Evidence: `build-ddr-seeds-tpu-counters/results.json` and the completed
`build-ddr-seeds-tpu-counters-rest/results.json`. Use the DMA runner's retained
packed/O3, system-mul, bus-payload, uart-control and command/write-buffer flags,
plus `--tpu-counters`, for system/stress/synthesis. `prove.py --n 4 --out ...`
reproduces the current wrapper proof. This proof does not cover other N values.

## Completed eight-seed comparison

| Seed | Baseline system MHz | Candidate system MHz | Candidate CPU MHz |
|---|---:|---:|---:|
| 1 | 75.37 | 79.27 | 92.55 |
| 2 | 70.34 | 68.41 | 95.65 |
| 3 | 76.17 | 73.82 | 90.46 |
| 4 | 81.57 | 85.82 | 95.19 |
| 5 | 78.61 | 76.20 | 95.19 |
| 6 | 79.42 | 76.01 | 87.15 |
| 7 | 81.14 | 81.22 | 89.49 |
| 8 | 70.20 | 79.58 | 92.01 |

System-clock mean across the same eight seeds: 76.603→77.541 MHz. Best system Fmax improves 81.57→85.82 MHz (+5.21%); four seeds improve and four regress. No seed closes 100 MHz. The narrowed counters are the current timing front-runner, with exact workload profiles preserved, but remain an opt-in experiment rather than a timing-qualified board default.
