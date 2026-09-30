# Explicit one-hot DDR bank FSMs — rejected

`generate.py` changes only BankMachine FSM encoding to explicit one-hot states
with matching initialization and reset, then lowers each state case to direct
bit tests. The real generated board has eight nine-state FSMs and 112 case
blocks. Control flow, timers, command sequencing, and native adapters stay
unchanged. Refresher and multiplexer FSMs are not changed.

`check.py` proves full bank-machine output/state equivalence using the binary
to one-hot state relation and runs 14 upstream bank tests at board geometry.
It covers reachable states from initialization/reset, arbitrary command,
refresh, and backpressure inputs. Illegal-state fault recovery is outside this
proof. Evidence: `build-ddr-onehot-explicit-bank/results.json`.

The earlier `prove.py` synthesis-hint approach did not actually recode the FSM.
Its no-op result in `build-ddr-onehot-bank/results.json` is explicitly failed;
the checker now requires an actual recoding log. Do not count it as evidence
for the explicit generator.

Built on narrow TPU counters, smoke profiles match and synthesis passes.
Both routes regress: seed 4 80.72 MHz system / 93.77 MHz CPU; seed 7
68.32 / 89.01 MHz. Evidence: `build-ddr-seeds-onehot-bank/results.json`.
This remains disabled, with no DDR electrical/calibration signoff claimed.
