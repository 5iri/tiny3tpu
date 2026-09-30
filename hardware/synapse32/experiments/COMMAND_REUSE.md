# Reuse invariant result-command batches

The packed RV32IM backend now keeps result commands in a separate part of the
existing DMA buffers. Commands 0–16 hold the packed operand load and START;
commands 17 onward hold up to 96 result commands. The template is rebuilt only
when the valid output tile dimensions change. The backend reuses it across K
chunks and compatible output tiles, eliminating repeated CPU stores to DDR.

This is firmware command reuse, not an instruction cache or concurrent DMA.
Each descriptor still completes before the next starts. A local descriptor
view selects the second buffer window; errors poison the parent driver, and
the caller's original buffer pointers remain unchanged. Capacities below 113
commands use the original construction path. Reuse is selected for K>8,
N>=8, or M>=8 with N<=4; other cases avoid setting up the second window.

## 45-shape comparison against the preceding `-O3` firmware

| Metric | Previous | Reuse |
|---|---:|---:|
| Full diagnostic system cycles | 15,601,564 | **12,029,963** |
| Useful MACs / total system cycle | 0.00462928 | **0.00600368** |
| GEMM system cycles | 9,541,773 | **5,971,575** |
| GEMM instructions | 1,420,931 | **910,347** |
| GEMM enabled CPU cycles | 1,643,125 | **1,103,023** |
| Pooled GEMM IPC | 0.864774 | 0.825320 |
| Equal-shape mean IPC | 0.844598 | 0.825786 |
| Useful PE capacity | 0.023654% | **0.037796%** |

The same 72,224 useful MACs take 22.9% fewer whole-test cycles, giving **29.7%
greater effective throughput**. GEMM-only cycles fall 37.4%. This is retained
under the useful-work-per-system-cycle objective, not an IPC-improvement claim:
IPC falls on all 45 shapes. Twenty-three GEMMs finish sooner and 22 smaller
cases regress, by at most 3.55% (4×7×5). Full per-shape results are in
`build-ddr-command-reuse/final-comparison/results.json`.

DMA traffic is identical: 137,970 beats and 9,874 bursts per direction. The
improvement comes from less firmware construction work and fewer CPU DDR
stores, not a change in matrix work or a reduction in DMA transfer volume.

## Validation

All 3,022 signed results pass. The final-source tests also pass:

- All 45 shapes with 96-command and 112-command fallback buffers, and the exact
  113-command cache boundary. Canaries immediately after both buffers survive.
- AXI read and write errors injected specifically on the cached result
  descriptor. The actual CPU firmware checks parent poisoning, completion
  acknowledgment, explicit reinitialization and
  successful subsequent GEMM. Caller buffer pointers remain unchanged.
- Legacy operand mode retains the previous exact PROFILE, METRICS and DMA
  records on the full sweep; it has no command-cache path.

No new ISA instructions, RTL, instruction cache, branch predictor or asynchronous
queue are added. The current code executes from on-chip boot RAM, through the
uncached SoC fetch sequencer. These are behavioral-memory measurements; full
diagnostic runtime includes boot, input generation and caller verification.

Use the existing packed build command with `--firmware-opt=-O3`. Evidence is in
`build-ddr-gemm-command-selective/system/results.json`,
`build-ddr-utilization-command-selective/results.json`,
`build-ddr-command-reuse/final-{cap96,cap112,cap113,read-error,write-error}/results.json`,
and `build-ddr-command-reuse/soc/results.json`.

The pre-change source is saved as `build-ddr-command-reuse/dma_backend_before.c`.
Board synthesis passes. The flattened hardware graph matches the previous
board exactly after normalizing generated source paths and excluding only boot
RAM contents; see `build-ddr-command-reuse/board-structure-final.json`. This is
a structural check, not a fresh route or 100 MHz signoff. The prior system
clock result remains 81.57 MHz, with the full 100 MHz target still open.

## Active versus system utilization

The same observed counters now report useful PE capacity over three windows:
0.018761% over the entire diagnostic, 0.037796% over GEMM calls, and **19.3817%**
over core-active PE cycles. Controller-active utilization, including local
operand loading, is 3.9225%. Both active-window figures are unchanged by command
reuse: the same tiles still execute; the firmware eliminates time between them.

Core-active capacity uses `useful_MACs / (16 * sum(two core-busy counters))`,
where core-busy includes CLEAR/FEED/FLUSH/CAPTURE. This is algorithmic useful
work divided by available active PE slots, not a PE-valid event counter.

The CPU-enabled/system-cycle ratio must not be read as avoidable stall time.
The staged integration requires at least four system clocks between enabled CPU
edges; intervening clocks perform staged CPU work and memory sequencing. The
18.5% enabled-edge fraction alone therefore does not prove 81.5% memory waiting.
The current GEMM partition is 647,863 DMA-only cycles, 45,956 TPU-only cycles,
11,584 overlapping cycles and 5,266,172 neither-busy cycles. CPU memory requests
are pending for 947,237 cycles, overlapping those categories. Neither-busy time
still needs finer attribution before labeling it starvation or idle waiting.
