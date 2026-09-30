# Packed-design seed sweep

Eight completed routes use the same latest retained packed-load firmware netlist, original 100 MHz constraints, nextpnr binary and chip database. Only the seed changes; placement environment overrides are cleared. Two routes run concurrently. All input hashes remained unchanged.

| Seed | System MHz | CPU MHz | System → CPU ns | CPU → system ns |
|---|---:|---:|---:|---:|
| 1 | 75.37 | 78.77 | 10.35 | 12.46 |
| 2 | 70.34 | 84.53 | 9.23 | 10.86 |
| 3 | 76.17 | 82.71 | 10.88 | 11.89 |
| 4 | 81.57 | 102.51 | 8.62 | 10.13 |
| 5 | 78.61 | 97.08 | 8.31 | 10.87 |
| 6 | 79.42 | 88.42 | 8.53 | 11.81 |
| 7 | 81.14 | 102.43 | 8.75 | 9.73 |
| 8 | 70.20 | 79.46 | 9.81 | 12.63 |

**Seed 4 remains best: 81.57 MHz system / 102.51 MHz CPU.** Seed 7 is close, but none closes 100 MHz. The latest retained firmware now has a fresh route, reproducing the earlier packed-hardware result. No seed is promoted as timing-clean.

Ranking uses the worst normalized margin across all reported constrained clocks and budgeted cross-clock paths. Strict acceptance additionally rejects the unsupported I/O-bank constraint warning. These are diagnostic nextpnr results, not DDR I/O, calibration, clock-gating or board signoff. No timing exceptions were introduced.

Seed-only routing changes no RTL or instruction sequence, so this sweep adds no architectural cycles. It does not establish measured board IPC or throughput.

Reproduce:

```sh
python3 tools/synapse32_seed_sweep.py --board build-ddr-dma-packed-loads/board --out build-seeds-new --seeds 1 2 3 4 5 6 7 8 --jobs 2
```

Evidence: `build-ddr-seeds-packed-loads/results.json` and `build-ddr-seeds-packed-loads-5-8/results.json`, with per-seed commands, hashes, raw routed reports and strict timing summaries.
