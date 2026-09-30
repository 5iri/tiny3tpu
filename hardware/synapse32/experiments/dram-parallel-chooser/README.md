# Parallel masked DDR command selection

This opt-in probe replaces dynamic array indexing in each DDR command chooser
with a masked OR of the bank signals. It shares bank grant comparisons and
uses local filtered validity for bank-ready outputs. Arbitration state,
request filtering, selected command values, and all handshake cycles remain
identical. The generator requires a power-of-two bank count; the board has eight.

`check.py` proves all eight-bank chooser outputs with equal arbitration state
for arbitrary requests, filters, ready and reset inputs, then runs all 14
upstream multiplexer tests. Evidence: `build-ddr-parallel-chooser/results.json`.

Use `dma/run.py --dram-parallel-chooser --csr-read-direct --tpu-counters` with
the retained DMA flags. The strict write adapter remains unchanged. Smoke
PROFILE, METRICS and DMA records match exactly; synthesis passes. The behavioral
SoC memory model does not instantiate the physical chooser, so formal proof
supplies the board-only cycle/command preservation check. Seed 4 improves to **88.20 MHz system / 98.59 MHz CPU**, with joint margin
−0.118; seed 7 reaches 82.28 / 105.76 MHz. Evidence:
`build-ddr-seeds-parallel-chooser/results.json`. This is the new opt-in routed
front-runner; all 45-shape PROFILE, METRICS and DMA records match exactly, and the
remaining six seeds are running. No 100 MHz
closure or physical DDR signoff is claimed.

The full eight-seed sweep is complete:

| Seed | System MHz | CPU MHz | Joint margin |
|---:|---:|---:|---:|
| 1 | 82.28 | 102.15 | -0.17720 |
| 2 | 88.75 | 96.11 | -0.11250 |
| 3 | 77.05 | 102.35 | -0.22950 |
| 4 | 88.20 | 98.59 | -0.11800 |
| 5 | 82.14 | 99.26 | -0.17860 |
| 6 | 82.23 | 93.21 | -0.17770 |
| 7 | 82.28 | 105.76 | -0.17720 |
| 8 | 95.39 | 100.52 | -0.04610 |

**Seed 8 is the current best: 95.39 MHz system / 100.52 MHz CPU**. Both
cross-clock paths pass 10 ns (9.10 and 9.82 ns). System timing remains about
0.48 ns short of the 10 ns target. Whole-system/IPC profiles remain exact;
DDR physical signoff limitations remain unchanged.
