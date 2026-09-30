# Enabled-cycle IPC audit

The original DMA smoke workload reports 221,485 instructions / 287,684 enabled
CPU edges = **0.769889879 IPC**. This is the complete firmware workload, not a
peak-issue benchmark. The fixed multiply workload separately measures
4,007 / 4,118 = **0.973045 IPC**.

An independent shadow of IF/ID and ID/EX validity tracks why each empty slot
was inserted. The audit also checks that the CSR cycle counter increments once
per measured enabled edge. On the no-fault/no-IRQ workload every edge belongs
to exactly one category:

| Category | Enabled cycles |
|---|---:|
| Instruction completed | 221,485 |
| Branch/jump redirect bubbles | 54,072 |
| Load-use bubbles | 7,769 |
| Divider waits | 4,356 |
| Startup fill | 2 |
| **Total** | **287,684** |

There are 27,036 redirects, each inserting two bubbles. All 132 REMU operations
in input-data generation contribute 33 waiting edges apiece. Disabled CPU clock
periods during DDR transactions are excluded from this denominator. The audit
rebuilds byte-identical firmware and reproduces the original instruction and
edge counts. The counter is EX completion on this workload, not precise trap
retirement.

The DDR selftest accounts for 123,344 instructions and 32,888 redirect bubbles.
The small `append` helper accounts for 6,759 of the 7,769 load-use bubbles.
`tiny3tpu_dma_qgemm` itself measures 0.835700 IPC with its attributed bubbles.
The complete per-function attribution and source evidence are in
`build-ddr-ipc-audit/results.json`.

```sh
python3 tools/synapse32_ipc_audit.py \
  --reference build-ddr-dma-system-decode --out build-ipc-audit-new \
  --dma-source build-ddr-firmware-inline/dma_backend_original.c
```

Firmware command-builder inlining subsequently reduces work and improves IPC:

| Workload | Original instructions / edges | Inlined instructions / edges | Original IPC | Inlined IPC | System cycles before → after |
|---|---:|---:|---:|---:|---:|
| Smoke, 35 results | 221,485 / 287,684 | 173,078 / 223,294 | 0.769890 | 0.775113 | 1,481,754 → 1,185,342 |
| Five shapes, 162 results | 463,196 / 614,386 | 306,842 / 405,428 | 0.753917 | 0.756835 | 3,153,588 → 2,189,877 |

Both retain identical DMA payload beat/burst counts and all expected signed
results. Smoke firmware shrinks from 5,688 to 5,512 bytes. This is a small IPC
gain and a larger reduction in total work; those are separate measurements.
The timing-oriented CPU overlays themselves retained the prior traces and IPC.

The post-inlining audit independently accounts for 223,294 enabled edges:
173,078 instruction completions, 44,154 redirect bubbles, 1,704 load-use
bubbles, 4,356 divider waits and two startup bubbles. There are 22,077 redirects.
Evidence is in `build-ddr-ipc-audit-inline/results.json`. Branch/jump flushes
still dominate; a clock-rate increase alone does not improve this IPC metric.

## Future option: branch prediction (deferred)

Branch prediction is a future systems improvement, explicitly deferred by the
user. No predictor implementation is part of the current timing work. The
post-inlining workload spends 44,154 of 223,294 enabled CPU cycles (19.77%) in
branch/jump redirect bubbles. This is an opportunity to investigate, not an
estimate of the cycles a predictor would necessarily recover.

Before selecting an implementation, extend the audit to distinguish conditional
branches, direct jumps/calls, indirect jumps and returns, with taken frequency
and hot PCs. Use that evidence to evaluate early target handling and prediction
options. Any future change must improve measured instructions per enabled CPU
cycle on the same firmware workloads, preserve architectural behavior and
exception/interrupt handling, and remain compatible with the 100 MHz timing
target. Keep enabled-cycle IPC and total system cycles as separate metrics.

The separate [TPU utilization audit](TPU_UTILIZATION.md) now measures activity
inside the GEMM calls, excluding boot and DDR self-test. It shows that the
current firmware/command transport leaves the arrays idle for most of each
call. Preserving CPU IPC remains a requirement, but it is insufficient to
establish accelerator throughput; both metrics must be tracked.
