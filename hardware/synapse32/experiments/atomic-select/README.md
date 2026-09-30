# Parallel atomic result selection

The traced CPU-to-system write-data path crosses atomic min/max comparison,
then a priority chain selecting the atomic result. This experiment changes
the mutually exclusive instruction selection into a `case (instr_id_mem)`.
All arithmetic, instruction IDs, controls and reservation-state transitions
are preserved. No instruction is removed and no pipeline stage is added.

`prepare.py` copies the four-file atomic-word CPU overlay and embeds the
renamed candidate module in `riscv_cpu.v`. Only its instance type changes;
other CPU bytes and the original sibling repository remain untouched.

`build-atomic-select/results.json` records inductive equivalence of all actual
atomic outputs, controls and reservation state for arbitrary instructions,
operands, addresses, reset and store notifications. The proof includes the
exact module embedded in the CPU and hashes both the source and overlay.

The motivating trace is
`build-ddr-write-limit8-timing-sensitivity/store-data-trace.json`: from EX/MEM
rs2 bit 9, through signed AMOMIN comparison, to sequencer request write-data
bit 28. Its zero-substitution interval is 11.724 ns. This is an optimization
diagnostic, not measured physical timing.

Smoke and all 45 GEMM shapes pass with every PROFILE, METRICS and DMA field
unchanged: `build-atomic-select/throughput-comparison.json`. Synthesis with
both DMA capacity changes uses 627 CARRY4, 6,478 LUT6, 7,411 FDRE, 6,366 FDCE,
36 DSP48E1 and 16 RAMB36E1. This adds 114 LUT6 over the DMA-only combination;
firmware and constraints remain byte exact. Routing must justify that cost.

It did not: expanded maxima for seed 4 are 14.800/14.800/15.200 ns and seed 8
13.703/13.703/14.003 ns (PCOUT/carry probes 0/0, 1/0, 0/0.1). Both are worse
than the retained DMA-capacity seed 4. This atomic rewrite remains unselected.
Hash verification: `build-atomic-select/route-integrity.json`.
