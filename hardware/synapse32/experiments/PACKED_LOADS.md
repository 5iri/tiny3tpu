# Reuse load headers and read aligned operands as words

The packed RV32IM backend retains two changes:

- With command-window reuse enabled, initialize load headers and START once.
  Each tile updates operand payloads and restores command zero, which polling
  overwrites. The other headers survive in the disjoint load window.
- For a complete four-byte operand row, use one aligned word load when the
  address permits it. A guarded `__builtin_assume_aligned` plus four-byte
  `__builtin_memcpy` preserves C aliasing rules. Unaligned rows use byte loads;
  tails retain their bounded byte loop. This uses the current little-endian
  RV32IM ABI and requires no new instructions, cache or RTL.

## 45-shape comparison

Both builds use packed commands and `-O3`, with 72,224 useful MACs and 3,022
checked results. The baseline is the preceding selective command-reuse build.

| Metric | Before | After |
|---|---:|---:|
| Full diagnostic system cycles | 12,029,963 | **11,544,608** |
| Useful MACs / total system cycle | 0.00600368 | **0.00625608** |
| GEMM system cycles | 5,971,575 | **5,479,755** |
| Pooled GEMM IPC | 0.825320 | 0.801148 |
| Equal-shape mean IPC | 0.825786 | 0.811653 |
| CPU external reads, full diagnostic | 213,905 | **187,736** |
| CPU external writes, full diagnostic | 59,814 | **49,212** |
| GEMM external data-wait cycles | 947,237 | **582,594** |

Whole-test throughput improves **4.20%**, GEMM cycles fall **8.24%**, and external
data-wait cycles fall **38.5%**. DMA traffic is unchanged at 137,970 beats and
9,874 bursts per direction. Header reuse alone took 11,953,981 whole-test cycles;
aligned operand reads account for most of the remaining gain. The header-only
`-O2` variant was slower and is not selected.

Twenty-six shapes finish sooner and 19 regress; the largest relative regression
is 7.63% for 1×1×1. IPC improves on only one shape. This is retained under the
useful-work-per-system-cycle objective, not as an IPC improvement. Full shape
results are in `build-ddr-load-reuse/comparison/results.json`.

## Exclusive sequencer-state accounting

The observer now counts all eight sequencer states within each GEMM window and
asserts that their sum equals its system-cycle count. The data-wait subcategories
also sum exactly. Instrumentation preserves the original firmware bytes, CPU
profiles, DMA counts and system metrics.

| State/category | Before | After |
|---|---:|---:|
| Instruction fetch request | 1,103,023 | 1,077,939 |
| Instruction fetch wait | 1,103,023 | 1,077,939 |
| CPU step edge | 1,103,023 | 1,077,939 |
| CPU settle | 1,103,023 | 1,077,939 |
| Data request | 369,418 | 331,305 |
| External data wait | 947,237 | 582,594 |
| Local data wait | 242,828 | 254,100 |
| Boot wait / fault within GEMM | 0 | 0 |

The four states per CPU step occupy **78.7%** of the new GEMM runtime. External
data wait occupies **10.6%**, local data wait **4.6%**, and data requests **6.0%**.
DMA-status access states total 46,036 cycles (0.84%); this is the register-access
time, not all instructions involved in polling.

The staged CPU integration requires four system clocks per enabled CPU edge.
These state counters are not evidence that those clocks are avoidable stalls.
Nor are they added to the DMA/TPU busy partition: the two partitions describe
the same timeline from different viewpoints. Memory is behavioral; no physical
DDR bandwidth/contention claim follows. Instruction fetch currently comes from
on-chip boot RAM and takes one request plus one wait state per enabled edge.

## Validation and artifacts

- All 45 shapes and 3,022 results pass, plus the separate smoke test.
- The complete sweep passes with signed-byte extremes, both aligned input
  bases and deliberately unaligned A+1/B+3 bases.
- Buffer-end canaries and pointer preservation pass at capacities 96 and 113.
- Cached-result read/write error injection, parent poisoning, acknowledgment,
  explicit reinitialization and subsequent GEMM all pass on the actual CPU.
- Legacy operand mode retains the exact prior PROFILE, METRICS and DMA records.
- The generated ELF has no unresolved memcpy dependency. Test text+data is
  15,320 bytes, within the existing on-chip boot-memory capacity.

Evidence: `build-ddr-gemm-packed-loads/system/results.json`,
`build-ddr-utilization-{command,packed-loads}-states/results.json`,
`build-ddr-load-reuse/{aligned-extremes,unaligned-extremes,cap96,cap113,read-error,write-error}/results.json`,
and `build-ddr-load-reuse/{comparison,soc}/results.json`.

Use the existing packed build command with `--firmware-opt=-O3`. The prior
source is `build-ddr-load-reuse/dma_backend_before.c`. Board synthesis passes. The flattened hardware matches the prior image
except boot RAM contents (generated source paths normalized), recorded in
`build-ddr-load-reuse/board-structure.json`. No fresh placement/routing or
100 MHz signoff is claimed; the earlier system timing limit remains open.
