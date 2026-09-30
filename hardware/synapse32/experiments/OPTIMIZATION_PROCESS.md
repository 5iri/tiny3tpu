# Timing and useful-work acceptance

Working baseline: divider-only CPU, original boot decode and CSR. This is an
experimental baseline, not timing-qualified hardware. CPU/system final routed
Fmax is 41.81/61.02 MHz at seed 4, with both targets still 100 MHz.

Every candidate must keep its source overlay separate until it passes:

1. Functional checks: relevant equivalence, CPU dependencies, cancellation,
   interrupts, memory ordering, and real-CPU memory-model-to-TPU workload.
2. Workload measurement: same firmware bytes, harness source, memory-model
   policy and seed; retain full successful logs and hashes. Record total system
   cycles, external read/write bytes, completed transactions, request stalls and
   response latency sum. These do not measure CPU IPC.
   The user's throughput definition is **instructions per CPU cycle**. Compare
   the same completed instruction stream and count enabled CPU clock edges;
   record system cycles separately because the CPU clock is gated. Require
   CPU IPC to be at least the baseline, with improvement as the objective.
   Higher MHz cannot compensate for a CPU IPC regression. A longer instruction
   latency is acceptable only if overlapping execution preserves measured IPC.
3. Physical comparison: same tool/chipdb, XDC, firmware, clocks and seed for
   initial A/B routing. Then use the same predeclared seed set for both baseline
   and promising candidate; report distribution, not just the best seed.
4. Joint assessment: retain correctness and check CPU IPC, workload cycles and
   both 100 MHz clock targets. A frequency gain does not establish an IPC gain. Mark
   any frequency-scaled simulation time as hypothetical, not board performance.
5. Independent Astra review before promotion. DDR IO/DCI, clock-enable timing,
   calibration and actual hardware checks remain separate acceptance gates.

The current workload includes boot, DDR-memory-model selftest, input setup,
5x11x7 signed GEMM, result verification and reporting. Its measurements are
neither isolated GEMM throughput nor JAX end-to-end execution time. CPU IPC,
phase-separated accelerator timing and physical transfer benchmarks cannot be
inferred from these counters. `mul-pipeline/benchmark.py` now measures CPU IPC
for a separate identical MUL-heavy instruction stream, checks the complete
instruction-completion trace, and rejects regressions. Its EX completion signal
is appropriate only for the benchmark's no-fault/no-interrupt scope with pipeline
drain; it does not establish precise retirement behavior on exceptions.

Baseline with the new observational metrics: 4,981,249 system cycles, 9,294
external reads (37,176 bytes), 8,400 writes (33,176 enabled bytes), 17,694
completed transactions, 5,955 request-stall cycles, and 177,454 summed response
latency cycles. All 35 results passed. Cycle count agrees with the earlier
uninstrumented test. The delay generator is cycle-indexed: changing execution
timing changes per-request delays, even with the same policy and initial seed.

Capture one successful workload per log and compare with:

```sh
python3 tools/synapse32_workload_report.py baseline.log candidate.log
```

Optional `--baseline-assumed-mhz` and `--candidate-assumed-mhz` provide explicitly
hypothetical elapsed-time comparisons. Use system-clock frequencies, not CPU
edge counts. Changing frequency in this calculation does not simulate different
DDR clock ratios or absolute memory service times.

Instruction buffering reduces sequencer fetch overhead but does not by itself
raise instructions per enabled CPU edge. The globally stalling multiplier and
extra divider setup cycle are excluded from the current candidate because they
add CPU stalls. Prefer combinational simplification and control retiming that
preserve CPU scheduling. Any future pipeline proposal still has hazard, trap,
and measured IPC obligations. Keep the BUFGCE/settle safety contract intact.
