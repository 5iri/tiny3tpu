# Explicit one-hot DDR refresher FSM

This opt-in probe targets the new CSR-direct route's system critical path,
which begins at the refresher state and crosses bank-control logic. Only the
Refresher FSM changes from binary encoding to four one-hot state bits. All
state decisions become direct bit tests, with matching initialization/reset.
Bank FSMs, timers, ZQCS scheduling, adapters and command sequencing stay intact.

`check.py` proves equal command outputs and all other sequential state under
the binary/one-hot state relation, using actual KC705 DDR3 geometry, 100 MHz
settings, ZQCS frequency 1 Hz and postponing 1. It also runs all three upstream
refresh tests. Evidence: `build-ddr-onehot-refresh/results.json`. The proof
covers reachable states from initialization/reset and arbitrary ready/reset
inputs, not fault-induced illegal states.

Use `dma/run.py --dram-onehot-refresh --csr-read-direct --tpu-counters` with
the retained DMA flags. Smoke PROFILE, METRICS and DMA records match exactly;
the behavioral memory model does not instantiate the physical refresher.
Formal equivalence supplies the board-only cycle/command preservation check.
The generated board has `builder_refresher_state = 4'd1`, and synthesis passes.
Both routes regress: seed 4 77.10 MHz system / 98.38 MHz CPU, seed 7
77.44 / 94.38 MHz. Evidence: `build-ddr-seeds-onehot-refresh/results.json`.
This candidate is rejected and remains disabled; no DDR signoff is claimed.
