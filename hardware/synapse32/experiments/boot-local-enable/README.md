# Local boot-RAM acceptance

The newly modeled boot RAM exposes a 10.173 ns enable path through request
address decoding and external-memory readiness. Boot memories up to 64 KiB at
0x80000000 cannot overlap either external region (DRAM or controller CSRs), so
external readiness cannot affect their acceptance.

The candidate directly qualifies RAM access with request valid, reset, local
idle and boot address. It retains the original enable expression for every
other BOOT_WORDS parameter value. Read/write bodies, response logic and CPU
sequencing are unchanged; no pipeline or bus cycle is added.

`build-boot-local-enable/results.json` proves the RAM block enable identical for
all addresses, reset, local state, request valid, external ready and every
signed 32-bit BOOT_WORDS value. The proof uses the generated SoC's actual decode
expressions. The opt-in DMA driver checks proof hashes and those expressions
before applying the patch.

Smoke and full 45-shape PROFILE, METRICS and DMA records are exactly equal to
the retained selector baseline:

- `build-ddr-dma-boot-local/system/results.json`: 106,588 instructions,
  142,895 enabled CPU edges and 789,205 system cycles.
- `build-ddr-gemm-boot-local/system/results.json`: 1,659,843 instructions,
  2,084,686 enabled CPU edges and 11,544,608 system cycles.

Synthesis passes with the same FDRE/FDCE, DSP, BRAM and carry counts.
The seed-8 baseline is reproduced with exactly equal routed JSON and Fmax
(`build-ddr-seeds-boot-control-graph/seed-8/control-reproduction.json`). The
read-only observer and the new RAM model produce this comparison:

| Route | System MHz | CPU MHz | System→CPU | CPU→system | RAM input max | RAM output max |
|---|---:|---:|---:|---:|---:|---:|
| Baseline seed 8 | 95.39 | 100.52 | 9.10 ns | 9.82 ns | 10.116 ns | 8.265 ns |
| Candidate seed 8 | 88.65 | 102.48 | 8.72 ns | 9.81 ns | 9.902 ns | 7.972 ns |
| Candidate seed 4 | 78.74 | 97.35 | 9.02 ns | 12.11 ns | 10.310 ns | 8.265 ns |

All 200 MHz side-clock groups pass the existing partial model in these runs.
The candidate removes the modeled RAM violation on seed 8, but overall system
timing is worse. It is **rejected as a replacement for the retained design**.
Evidence: `build-ddr-seeds-boot-local-graph/results.json`. Full-SoC acceptance
stays false while other DSP, distributed-memory and primitive-delay gaps remain.
No board defaults or sibling CPU sources are changed.

```sh
python3 hardware/synapse32/experiments/dma/run.py system --out build-boot-new \
  --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul \
  --bus-payload --uart-control --dram-command-buffer --dram-write-buffer \
  --packed-rows --firmware-opt=-O3 --tpu-counters --csr-read-direct \
  --dram-parallel-chooser --boot-local-enable
```

Use the same arguments for synthesis after validation. The candidate remains
an isolated, functionally equivalent experiment; the routing regression prevents promotion.
