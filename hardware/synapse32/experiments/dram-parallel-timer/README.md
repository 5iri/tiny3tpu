# Parallel selection plus registered refresh terminal count

This composes two independently proven cycle-equivalent components: the
parallel masked bank chooser and the refresh/ZQCS timer's registered terminal
flag. The 95.39 MHz selector-only route starts its critical path at the 27-bit
ZQCS zero comparison; registering the predicted flag removes this decoder
without changing any request cycle.

`verify.py` checks both proof manifests and source hashes, applies the actual
patches, verifies byte-identical candidate sources, and runs all 17 combined
upstream refresh/multiplexer tests. Evidence: `build-ddr-parallel-timer`.
The strict WRITE-DRAIN adapter and two-entry wide write buffer are retained.

Use both `--dram-parallel-chooser --dram-refresh-timer` with the retained flags,
`--tpu-counters --csr-read-direct`. This is the only newly allowed pair among
the otherwise mutually exclusive DDR experiments. Synthesis checks both
component proofs and the composition evidence before building.

Smoke PROFILE, METRICS and DMA are unchanged; synthesis passes. Seed 4 gives
90.93 MHz system / 106.83 MHz CPU, with a 10.03 ns CPU→system crossing. Seed 7
reaches 85.84 / 102.64 MHz. Seed 8 reaches only 78.53 MHz system / 110.01 MHz CPU. This does not supersede the
selector-only best route yet, and is not DDR physical signoff.

The combination does not beat the selector-only best and remains disabled.
Evidence: `build-ddr-seeds-parallel-timer` and `build-ddr-seeds-parallel-timer-8`.
