# Registered Wishbone transaction enables — rejected

The opt-in `--wb-active` experiment captures control/DDR target-active bits on the existing request acceptance edge and clears them on the existing ACK/ERR completion edge. These bits directly drive target CYC/STB. Response address decoding is unchanged. No extra bus or CPU cycle is introduced.

`prove.py` uses the unchanged bridge and the exact candidate register block. Yosys temporal induction proves equality with the original decoded CYC/STB on every cycle from reset-equivalent initialization, with arbitrary requests, slave ACK/ERR, response backpressure and repeated resets. The generated board transformer and proof inputs are hashed.

CPU/DMA/TPU behavioral smoke test passes with exact PROFILE/METRICS/DMA equality: 106,588 instructions / 142,895 enabled CPU edges, 789,205 system cycles, 1,130 beats and 87 bursts per direction. This model does not instantiate the physical Wishbone frontend; formal proof covers the changed board signals. Synthesis passes.

| Seed | Baseline system / CPU MHz | Candidate system / CPU MHz | Candidate CPU → system ns |
|---|---:|---:|---:|
| 4 | 81.57 / 102.51 | 68.57 / 90.62 | 11.72 |
| 7 | 81.14 / 102.43 | 78.38 / 97.73 | 10.62 |

Both matched seeds regress; the remaining six baseline seeds were not run for this rejected candidate. The experiment remains disabled. No timing-clean design or hardware signoff is claimed; the unsupported I/O-bank warning persists.

Seed 4 critical path: DDR ZQCS timer count to controller register enable, 14.6 ns (2.2 ns logic / 12.4 ns routing). Seed 7: DDR sequencer completion to register enable, 12.8 ns (2.1 ns logic / 10.7 ns routing). These results motivate investigating DDR control fanout and physical locality; they do not establish that registering these maintenance signals would preserve protocol timing.

Reproduce:

```sh
python3 hardware/synapse32/experiments/wb-active/prove.py --out build-ddr-wb-active
# Run system then synth, with the same flags:
python3 hardware/synapse32/experiments/dma/run.py system --out build-ddr-dma-wb-active --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul --bus-payload --uart-control --dram-command-buffer --dram-write-buffer --packed-rows --firmware-opt=-O3 --wb-active
python3 tools/synapse32_seed_sweep.py --board build-ddr-dma-wb-active/board --out build-active-seeds-new --seeds 4 7 --jobs 2
```

Evidence: `build-ddr-wb-active/results.json`, `build-ddr-dma-wb-active/system/results.json`, `build-ddr-dma-wb-active/board/synth.log`, and `build-ddr-seeds-wb-active/results.json`.
