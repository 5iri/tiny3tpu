# Reset fanout replication

`prepare_unique.py` creates two copies of the existing final FDPE reset stage
and partitions synchronous and asynchronous reset pins from ordinary logic
loads. Copies retain the exact original INIT, D, CE, clock and asynchronous
PRE; no stage or cycle is added. A primitive-model proof and reversal of every
edit verify digital equivalence and exact original design recovery. Original
firmware, constraints, synthesis inputs and source netlist are hashed.

The first allocator (`prepare.py`) considered connected cell bits only and
reused two unused debug-net bits. No connected cell or top port was affected,
but those artifacts are excluded from selection. `prepare_unique.py` reserves
all cell, port and netname bits, including unused names. Earlier artifacts and
the allocation audit remain in `build-ddr-reset-replica-board`.

`build-ddr-reset-replica-unique-board` is the corrected current-UART-local
composition. Seed 4 reports 86.02/110.90 MHz system/CPU and expanded intervals
13.190/13.190/13.605 ns. The UART-read/divider composition is
`build-ddr-uart-read-divsign-replica-board`; seeds 4/8 report 93.17/102.72 and
92.75/83.63 MHz. None establishes 100 MHz or physical reset recovery/removal
and metastability behavior.

An independent placement-preserving experiment in
`tools/synapse32_local_reset_clusters_lut.py` copies the same final stage only
for 125 combinational reset loads in four geometric groups. It uses the prior
97.53 MHz layout, whose firmware and full workload records match current
measurements exactly (`build-ddr-dma-parallel-chooser-revalidated/current-performance-comparison.json`).
Normal placement legality and complete collapsed logical equivalence pass in
`build-ddr-local-reset-logic-clusters4-lut`. The first site-selection trial
selected a LUTRAM slice and was rejected by the original legality checker;
no checks were bypassed. Full reroutes at seeds 2/4 report 95.61/101.68 and
94.38/101.17 MHz. Timing models remain incomplete.
