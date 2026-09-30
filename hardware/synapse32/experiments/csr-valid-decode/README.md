# Factored CSR validity ranges

This opt-in probe includes direct CSR reading, then replaces the three full
address range comparisons (B03–B1F, B83–B9F, 323–33F) with shared high-address
matches and a low-five-bit comparison to three. The low comparison is written
as OR of bits 4:2 or AND of bits 1:0. All supported/unsupported addresses and
CSR values remain unchanged, including privileged and counter CSRs.

The exact combinational read/validity cones are proven equal for every 12-bit
address, read enable and arbitrary CSR register state. Sequential logic stays
byte-identical. Evidence: `build-csr-valid-decode/results.json`.

Use `dma/run.py --csr-valid-decode --tpu-counters` with the retained DMA flags;
`--csr-valid-decode` implies direct reading. The sibling CPU is untouched.
Smoke and all 45-shape PROFILE, METRICS and DMA records are exactly unchanged.
Synthesis passes, but both routes regress: seed 4 74.98 MHz system / 89.41 MHz
CPU; seed 7 74.31 / 98.39 MHz. Evidence:
`build-ddr-seeds-csr-valid-decode/results.json`. This candidate is rejected
and remains disabled.
