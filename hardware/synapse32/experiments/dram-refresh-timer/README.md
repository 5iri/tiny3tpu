# Registered refresh timer zero flag — not retained

This opt-in `--dram-refresh-timer` candidate registers the terminal-count flag
alongside the timer update. On decrement it predicts `count == 1`; on reload it
sets the flag according to the reload value. This removes the combinational
wide zero comparison from the downstream refresh/ZQCS request path without
moving a request by a cycle. The installed LiteDRAM source is not modified;
the board generator applies a checked transformation in memory and saves both
source versions. The corrected WRITE-DRAIN and two-entry write buffer remain.

Yosys temporal induction proves actual generated timer count and done outputs
identical under arbitrary wait and reset inputs, for periods 1, 2, 3, 8, 9,
782 (board refresh) and 100,000,000 (board ZQCS). All three upstream refresh
unit tests pass. Board-generated refresher source matches the proved source.
This proves timer behavior, not DDR electrical operation.

CPU/DMA/TPU behavioral smoke PROFILE, METRICS and DMA records are identical to
the retained firmware: 106,588 instructions, 142,895 enabled CPU edges,
789,205 system cycles, 1,130 beats and 87 bursts per direction. The behavioral
memory model does not exercise the physical DDR frontend; timer equivalence
and upstream tests cover the changed component. Synthesis passes.

| Seed | Baseline system / CPU MHz | Candidate result |
|---|---:|---|
| 4 | 81.57 / 102.51 | Placement validity failure; no routed Fmax |
| 7 | 81.14 / 102.43 | 75.83 / 89.13 MHz, regression |

Seed 4 fails nextpnr's post-placement validity check for
`SLICE_X74Y18/A5FF` (no cell). This was not bypassed or counted as a timing
result. Seed 7's worst system path is refresher-state control to a bank-machine
register enable via command-buffer readiness: 13.2 ns, including 11.5 ns
routing and 1.7 ns logic. The candidate remains disabled; there is no evidence
of a timing improvement and no reason to expand its seed sweep. The retained
packed design remains at 81.57 MHz system / 102.51 MHz CPU. Full 100 MHz closure
and DDR hardware signoff are outstanding. The unsupported I/O-bank constraint
warning remains.

Reproduce proof and tests:

```sh
.venv-ddr-compat/bin/python hardware/synapse32/experiments/dram-refresh-timer/check.py --out build-ddr-refresh-timer --upstream /tmp/tiny3tpu-litedram-2024.12-tests
```

Run `dma/run.py system`, then `synth`, with:

```text
--out build-ddr-dma-refresh-timer --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul --bus-payload --uart-control --dram-command-buffer --dram-write-buffer --packed-rows --firmware-opt=-O3 --dram-refresh-timer
```

Then route the fixed netlist:

```sh
python3 tools/synapse32_seed_sweep.py --board build-ddr-dma-refresh-timer/board --out build-refresh-seeds-new --seeds 4 7 --jobs 2
```

Evidence: `build-ddr-refresh-timer/results.json`,
`build-ddr-dma-refresh-timer/system/results.json`,
`build-ddr-dma-refresh-timer/board/synth.log`, and
`build-ddr-seeds-refresh-timer/results.json`, including the failed placement log.
