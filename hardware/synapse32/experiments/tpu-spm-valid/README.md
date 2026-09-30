# TPU input scratchpad ownership

This opt-in probe uses one validity bit per A/B scratchpad element. Payload
storage has no reset; unowned elements read as architectural zero. A load sets
ownership and stores the new value on the same edge. Reset clears ownership.
Busy gating, partial loading, result storage, array inputs and scheduling are
unchanged. Narrow phase counters are included.

The N=4 compositional proof checks every architectural scratchpad value, all
wrapper state and outputs, and all array inputs against the original wrapper,
for arbitrary loads, starts, reads, resets and shared array results. The array
itself is unchanged. Evidence: `build-tpu-spm-valid/results.json`.

Use `--tpu-spm-valid --csr-read-direct --dram-parallel-chooser` with the retained
DMA flags. The generated wrapper is used in both simulation and synthesis;
root RTL and sibling CPU remain unchanged. Smoke and all 45-shape PROFILE, METRICS and DMA records match exactly.
Synthesis passes and reduces resettable FDCEs by 448, but adds 512 FDREs:
no additional RAM32M cells were inferred. It removes reset loads but is not
an area reduction in this mapping. Seed 4/8 routes are running; no timing
gain is claimed until those routes complete.

Both routes regress: seed 4 82.93 MHz system / 105.76 MHz CPU, seed 8
86.15 / 94.30 MHz. Evidence: `build-ddr-seeds-tpu-spm-valid/results.json`.
The experiment is rejected and remains disabled.
