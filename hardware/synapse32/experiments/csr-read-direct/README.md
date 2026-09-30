# Direct CSR read decoding

The CSR read case already selects zero for every unsupported address. This
experiment removes `csr_valid` from the outer read-enable condition, leaving
`csr_valid` itself and all sequential CSR behavior unchanged. No instruction,
clock, latency, or architectural feature is added or removed.

`prove.py` extracts the exact read cone from the original and patched source,
exposes every CSR state register as an arbitrary shared input, and proves equal
`read_data` and `csr_valid` for every address and read-enable value. This is
stronger than testing only reachable CSR states. The remaining source is
byte-identical. Evidence: `build-csr-read-direct/results.json`.

Use `dma/run.py --csr-read-direct` with the retained flags and `--tpu-counters`.
Generated simulation and synthesis source lists both replace `csr_file.v`;
the sibling CPU checkout is untouched. Synthesis requires current proof hashes
and an exact matching generated candidate. Smoke and all 45-shape PROFILE, METRICS and DMA records are exactly unchanged.
Synthesis passes. Seed 4 reaches **87.60 MHz system / 91.24 MHz CPU**,
seed 7 reaches **85.55 / 90.73 MHz**. Evidence is in
`build-ddr-seeds-csr-read-direct/results.json`. This is the new opt-in front-runner;
the full eight-seed sweep is complete (mean system Fmax 84.37125 MHz, versus
77.54125 MHz for counter-only). It is not 100 MHz closure or physical DDR
signoff, and the unsupported bank constraint warning remains.

| Seed | System MHz | CPU MHz | Joint margin |
|---:|---:|---:|---:|
| 1 | 85.20 | 89.05 | -0.14800 |
| 2 | 84.38 | 94.68 | -0.15620 |
| 3 | 75.80 | 93.98 | -0.24200 |
| 4 | 87.60 | 91.24 | -0.12400 |
| 5 | 85.11 | 87.15 | -0.14890 |
| 6 | 85.82 | 90.79 | -0.16318 |
| 7 | 85.55 | 90.73 | -0.14450 |
| 8 | 85.51 | 96.11 | -0.14490 |

Joint margin includes cross-clock paths; seed 6 is limited by a crossing
rather than either reported within-domain Fmax. No seed closes 100 MHz.
