# UART local acceptance


## Current composition — selected diagnostic candidate

Composing this change with atomic-word/UART/boot decode and both DMA burst
capacity changes improves the original-backend expanded route comparison at seed 8.
The subsequent placed carry-guidance backend improves the same netlist further
at seed 4: 12.398/12.398/12.552 ns. See [carry guidance](../carry-guidance/README.md).
Proof is regenerated against the exact current SoC integration; the driver now
accepts `--uart-local-accept-proof build-uart-local-burst-proof` and validates its
hashes and exact generated candidate before simulation and synthesis.

| Route seed | PCOUT/carry = 0/0 ns | 1/0 ns | 0/0.1 ns |
|---|---:|---:|---:|
| 4 | 13.745 | 13.745 | 14.525 |
| 8, best original backend | 12.510 | 12.510 | 12.710 |
| Previous DMA candidate, seed 4 | 12.831 | 12.831 | 13.031 |

All entries are expanded timing sensitivity intervals in ns. The carry and
PCOUT delay substitutions are symbolic, not validated Kintex delays. Native
nextpnr reports 91.89 MHz system / 108.99 MHz CPU for original-backend seed 8, with
incomplete primitive coverage. Neither result establishes physical Fmax or
100 MHz closure. That route's worst zero-substitution endpoint is DDR width-converter
`memory.main_litedramnativeportconverter1_sel[14]`.

The complete smoke and 45-shape PROFILE/METRICS/DMA records match the preceding
DMA candidate exactly: full workload 11,544,608 system cycles, 1,659,843
instructions / 2,084,686 enabled CPU edges = 0.796208 IPC. GEMM windows retain
5,479,755 system cycles and 0.801148 pooled IPC. Firmware and XDC bytes match.
Synthesis uses 627 CARRY4, 6,439 LUT6, 7,411 FDRE, 6,366 FDCE, 36 DSP48E1 and
16 RAMB36E1. This adds 75 LUT6 versus the preceding DMA candidate; the measured
route improves despite that area increase. Board defaults remain unchanged.

Evidence: `build-uart-local-burst-proof/{results,throughput-comparison,synthesis-comparison}.json`,
`build-ddr-dma-uart-local-burst`, `build-ddr-gemm-uart-local-burst`,
`build-ddr-seeds-uart-local-burst-graph/seed-{4,8}`, and
`build-ddr-uart-local-burst{4,8}-timing-sensitivity`.

Use the preceding DMA candidate's recorded configuration with
`--uart-local-accept --uart-local-accept-proof build-uart-local-burst-proof`.
The proof command is:

```sh
python3 hardware/synapse32/experiments/uart-local-accept/prove.py \
  --soc build-ddr-dma-burst-limit/synapse32_dram_soc.sv \
  --out build-uart-local-burst-proof
```

## Historical standalone experiment — not retained

The MHz values in this historical section use incomplete timing coverage and do not establish whole-SoC Fmax.

Tracing the preceding local-ready candidate revealed that its reset critical path ended at a UART register enable, not a DDR bank register. Its reset net had 10,449 synthesized input loads. The UART enable used shared request acceptance, which includes external DDR request readiness even though UART and DDR address ranges are disjoint.

This opt-in `--uart-local-accept` experiment substitutes `!rst && idle && req_valid && uart_address` for `accept && uart_address` in both UART read and write enables. Reset gating and cycle behavior are preserved. The original top and sibling CPU are not edited. The candidate is applied to the retained hardware without rejected DDR changes.

Combinational SAT equivalence passes for the exact original integration declarations and candidate expression under all addresses, write strobes, read/write directions, idle/reset states and external-ready values. Synthesis requires fresh proof-source hashes and an exact match to the proved candidate SoC. The CPU/DMA/TPU smoke test retains exact PROFILE/METRICS/DMA: 106,588 instructions, 142,895 enabled CPU edges, 789,205 system cycles, 1,130 beats and 87 bursts per direction. Synthesis passes.

| Seed | Baseline system / CPU MHz | Candidate system / CPU MHz | System → CPU ns | CPU → system ns |
|---|---:|---:|---:|---:|
| 4 | 81.57 / 102.51 | 71.24 / 84.95 | 9.15 | 11.74 |
| 7 | 81.14 / 102.43 | 80.01 / 89.88 | 8.44 | 10.74 |

Both matched seeds regress. The experiment remains disabled; no expanded seed sweep is justified by these results. Retained system/CPU timing remains 81.57/102.51 MHz. No reset delay, clock exception or constraint change was introduced. Full 100 MHz closure and DDR hardware signoff remain outstanding; the unsupported I/O-bank warning persists.

Evidence: `build-ddr-uart-local-accept/results.json`, `build-ddr-dma-uart-local-accept/system/results.json`, `build-ddr-dma-uart-local-accept/board/synth.log`, and `build-ddr-seeds-uart-local-accept/results.json`.

Reproduce proof:

```sh
python3 hardware/synapse32/experiments/uart-local-accept/prove.py --soc build-ddr-dma-packed-loads/synapse32_dram_soc.sv --out build-ddr-uart-local-accept
```

Run `dma/run.py system`, then `synth`, with:

```text
--out build-ddr-dma-uart-local-accept --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul --bus-payload --uart-control --dram-command-buffer --dram-write-buffer --packed-rows --firmware-opt=-O3 --uart-local-accept
```

Then use `tools/synapse32_seed_sweep.py` with that board directory and seeds 4 and 7.
