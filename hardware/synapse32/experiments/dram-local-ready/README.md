# Bank-local command-ready validity — not retained

The opt-in `--dram-local-ready` change replaces the command chooser's global
selected-valid dependency in each bank ready output with that bank's own
filtered validity. The grant comparison remains present. For the selected bank
these values are identical; all other banks remain not ready. Arbitration,
command filtering, command payloads and transaction cycles are unchanged.
The installed LiteDRAM source is unchanged; the generator patches it in memory
and saves original/candidate evidence. The corrected WRITE-DRAIN path remains.

The complete generated eight-bank chooser passes Yosys temporal induction on
all outputs and the unchanged grant state, under arbitrary requests, filters,
backpressure and reset. Explicit grant-state equality strengthens induction:
output equality alone does not establish identical internal grants while idle.
All 14 upstream multiplexer tests pass. Board-generated multiplexer source
matches the proved candidate exactly.

CPU/DMA/TPU behavioral smoke passes with exact PROFILE/METRICS/DMA equality:
106,588 instructions / 142,895 enabled CPU edges, 789,205 system cycles,
1,130 beats and 87 bursts per direction. This memory model does not instantiate
the physical DDR frontend; chooser proof and multiplexer tests cover the changed
component. Synthesis passes.

| Seed | Baseline system / CPU MHz | Candidate system / CPU MHz | System → CPU ns | CPU → system ns |
|---|---:|---:|---:|---:|
| 4 | 81.57 / 102.51 | 80.46 / 107.35 | 8.49 | 9.28 |
| 7 | 81.14 / 102.43 | 74.26 / 98.52 | 8.91 | 9.65 |

Both system-clock results regress. CPU Fmax and cross-clock improvements at
seed 4 do not compensate for lower system Fmax. The experiment remains disabled;
remaining baseline seeds were not run for this candidate. Both new worst system
paths start at the DDR-generated system reset and end at register enables:
seed 4 takes 12.4 ns (1.4 logic / 11.0 routing), seed 7 takes 13.5 ns
(1.4 logic / 12.1 routing). Reset fanout and its interaction with register enables
are now a concrete follow-up target. No reset timing exception was introduced.

Retained packed-design timing remains 81.57 MHz system / 102.51 MHz CPU. Full
100 MHz closure and DDR hardware signoff remain outstanding. The unsupported
I/O-bank constraint warning persists.

Reproduce proof/tests:

```sh
.venv-ddr-compat/bin/python hardware/synapse32/experiments/dram-local-ready/check.py --out build-ddr-local-ready --upstream /tmp/tiny3tpu-litedram-2024.12-tests
```

Run `dma/run.py system`, then `synth`, with:

```text
--out build-ddr-dma-local-ready --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul --bus-payload --uart-control --dram-command-buffer --dram-write-buffer --packed-rows --firmware-opt=-O3 --dram-local-ready
```

Then route:

```sh
python3 tools/synapse32_seed_sweep.py --board build-ddr-dma-local-ready/board --out build-local-ready-seeds-new --seeds 4 7 --jobs 2
```

Evidence: `build-ddr-local-ready/results.json`,
`build-ddr-dma-local-ready/system/results.json`,
`build-ddr-dma-local-ready/board/synth.log`, and
`build-ddr-seeds-local-ready/results.json`.
