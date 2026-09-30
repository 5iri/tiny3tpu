# Divider final sign selection

The last quotient bit now selects upper negation alternatives computed in
parallel with the trial comparison. Remainder negation uses `divisor-trial`
in parallel, avoiding subtraction followed by negation. Launch, iteration,
reset, cancel and completion edges are unchanged.

`build-divider-sign-select-proved/results.json` proves full-module sequential
equivalence (268 comparison points). The original unit suite passes 16,437
arithmetic cases and 33 cancellation boundaries with exact latency. Fresh
smoke and all 45 GEMM shape PROFILE/METRICS/DMA records remain identical.

The UART reset-control composition's original-backend seeds 4/8 report
85.36/100.58 and 86.13/104.68 MHz system/CPU. These partial reports do not close
100 MHz. The subsequent parallel UART readback composition is documented in
[UART readback](../uart-read-parallel/README.md). Evidence resides in
`build-ddr-{dma,gemm}-uart-reset-divsign` and
`build-ddr-seeds-uart-reset-divsign-original-graph`.
