# Constant TPU feed-slot decoding — rejected

This opt-in experiment extends narrow phase counters with constant-index
selection of each A/B scratchpad feed value. Each `(row,column)` pair is selected
when `t_count == row + column`; default feed values remain zero.

N=4 compositional wrapper equivalence passes, with unchanged array internals
represented by shared arbitrary results. Smoke and all 45 GEMM shapes retain
exact PROFILE, METRICS and DMA records. Evidence: `build-tpu-feed-decode`,
`build-ddr-dma-tpu-feed-decode`, and `build-ddr-gemm-tpu-feed-decode`.

Routes regress: seed 4 reaches 80.13 MHz system / 94.55 MHz CPU; seed 7 reaches
76.41 / 102.04 MHz. See `build-ddr-seeds-tpu-feed-decode/results.json`.
The experiment remains disabled; the counter-only front-runner is better.
These are diagnostic nextpnr results, with the unsupported DDR bank constraint
and physical DDR signoff limitations unchanged.
