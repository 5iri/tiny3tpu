# Resetless wide DDR write payload — rejected

This experiment removes reset only from the native upconverter's wide write
payload. Ownership, valid, first/last, count, and all control reset behavior stay
unchanged. It retains WRITE-DRAIN command ordering and the two-entry wide write
FIFO. Unowned payload bits are unobservable.

Temporal induction preserves occupied lanes, valid full words, and handshake
timing for arbitrary valid/data/ready/reset inputs. `sink.last=0` matches the
actual board path. All 22 adapter tests, including strict scheduled writes,
pass. Evidence: `build-ddr-resetless-write/results.json`.

Built on narrow TPU counters, the smoke profile is unchanged, and synthesis
reduces reset fanout from 10,307 to 9,162 loads. Routes nevertheless regress:
seed 4 79.03 MHz system / 98.32 MHz CPU, seed 7 74.58 / 92.12 MHz.
Evidence: `build-ddr-seeds-resetless-write` and
`build-ddr-seeds-resetless-write-7`. The experiment remains disabled.
The behavioral SoC memory model is not physical DDR validation; equivalence
and component tests supply the adapter check. No hardware signoff is claimed.
