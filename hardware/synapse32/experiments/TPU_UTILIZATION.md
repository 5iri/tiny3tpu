# GEMM-scoped systolic utilization

CPU IPC alone does not establish accelerator throughput. The current diagnostic
firmware leaves both arrays idle for most of each GEMM call, even after excluding
boot, DDR self-test, caller input generation and caller result verification.

| GEMM M×K×N | System cycles in call | Average core-busy time | Useful PE capacity | Neither DMA nor TPU busy |
|---|---:|---:|---:|---:|
| 5×11×7 | 324,041 | 0.04197% | 0.003713% | 93.80% |
| 1×1×1 | 31,025 | 0.05479% | 0.000101% | 93.83% |
| 4×8×4 | 56,476 | 0.03010% | 0.007083% | 94.48% |
| 7×13×9 | 522,885 | 0.03901% | 0.004895% | 93.95% |
| 8×16×8 | 419,050 | 0.03245% | 0.007636% | 94.05% |
| 3×5×6 | 88,138 | 0.03858% | 0.003191% | 94.32% |

There are two 4×4 arrays (32 PE slots per system clock). Core-busy time counts
the CLEAR/FEED/FLUSH/CAPTURE states and averages the two cores. Useful PE capacity
is `M*K*N / (32 * call_system_cycles)`. Its numerator is the required algorithmic
MAC count, including legitimate zero-valued operands but excluding padding. It
is not a count of nonzero multiplications or raw accumulator updates; the RTL
PEs update even when processing idle zeros and have no useful-MAC valid signal.

Each accepted tile launch schedules 128 MACs across the two cores. Each core is
busy for 17 clocks, so even a fully populated tile uses only **23.53%** of PE
slots during core-busy time. Separately, the top-level controller spends 64
clocks copying operand bytes into core scratchpads, and is busy for 84 clocks
per launch. Thus an 80–95% utilization target is not a universal expectation
for this short, separately loaded tile schedule.

The dense 8×16×8 case has no padding: eight launches, 1,024 useful MACs, 136 busy
clocks per core, and 394,131 clocks with both DMA and TPU idle. The software and
command transport dominate this model. DMA currently carries register-command
packets: each operand byte requires three register writes, with acknowledgments,
and firmware serializes command construction, submission, completion checking
and result collection. This is not a packed tensor stream feeding the arrays.

Inside the dense call, the CPU completes 59,823 instructions in 73,773 enabled
edges (**0.810906 IPC**) for only 1,024 useful MACs. CPU memory requests are
outstanding during 96,246 of the 419,050 system cycles (**22.97%**). This latter
counter overlaps other activity and is not an exclusive stall category. The
call therefore demonstrates reasonable enabled-cycle CPU IPC alongside very
low accelerator utilization, with both software work and CPU memory latency
contributing to elapsed time.

The next throughput investigation should target packed operand/result transfers,
reduced per-command responses, and queued or double-buffered tile execution using
ordinary RV32IM descriptor code. Longer accumulation streams could also amortize
fill/drain. Branch prediction remains deferred. These are future changes, not
features implemented by this measurement.

## Scope and reproduction

```sh
python3 tools/synapse32_tpu_utilization.py --reference build-ddr-dma-control-payload --out build-ddr-utilization-smoke --dma-source build-ddr-firmware-status/dma_backend_before.c
python3 tools/synapse32_tpu_utilization.py --reference build-ddr-dma-control-payload-stress --out build-ddr-utilization-stress --dma-source build-ddr-firmware-status/dma_backend_before.c
```

The observer delimits calls using the existing ELF entry/return PCs, samples
RTL state and AXI handshakes, and checks exact firmware bytes, CPU profiles,
trace hashes, DMA counts and system metrics against the reference. All 35 smoke
and 162 stress results remain correct. Accepted launches, local loading clocks
and the exclusive DMA/TPU busy-state partition are checked against the workload.

These are behavioral-memory simulation measurements, not physical DDR3
bandwidth or starvation measurements. CPU memory delays, firmware preparation
and validation can all occur while DMA and TPU are idle. Backpressure counters
overlap other activity counters and are not a causal stall breakdown. Direct
DDR contention, physical calibration and Ethernet are not simulated here.

## Packed-row follow-up

[PACKED_ROWS.md](PACKED_ROWS.md) reports the implemented opt-in transfer path.
The dense call falls to 253,039 cycles and improves IPC to 0.817015; useful PE
capacity rises to 0.012646%. The table above remains the legacy baseline.
