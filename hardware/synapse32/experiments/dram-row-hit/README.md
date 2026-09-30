# Bank row-hit lookahead

The UART-control/divider-payload board's system-clock critical path runs from
a bank's held command address through row comparison and arbitration to another
bank's FIFO count enable (11.83 ns). This candidate maintains the row-hit bit
alongside the command and open-row registers, avoiding a combinational row
comparison in command eligibility.

On row opening, the held command necessarily matches the newly opened row.
Otherwise, whenever the command buffer can capture a replacement, its incoming
row is compared with the held open-row register at that same edge. The bit is
meaningful only while a command is valid. No queue depth, command ordering,
ready/valid timing, auto-precharge behavior or DDR timing rule changes.

Formal temporal induction compares all external signals, common stored state
and FIFO contents with upstream. It also proves the owned row-hit relationship
and the FSM validity invariants needed to establish that relationship. These
invariants are assertions proved from initialization, not assumed input
restrictions. Requests, command readiness and refresh inputs remain arbitrary.

Both the upstream test geometry and KC705 DDR3 geometry/timings pass induction;
the latter uses MT8JTF12864 at 100 MHz, 14 row bits, 10 column bits, four PHY
phases and CWL=5. All 14 upstream bank-machine simulation tests pass, covering
row changes, auto-precharge, burst preservation, locks, refresh and timing.

```sh
.venv-ddr-compat/bin/python hardware/synapse32/experiments/dram-row-hit/check.py --upstream /tmp/tiny3tpu-litedram-2024.12-tests --out build-ddr-row-hit
.venv-ddr-compat/bin/python hardware/synapse32/experiments/dram-row-hit/check.py --upstream /tmp/tiny3tpu-litedram-2024.12-tests --out build-ddr-row-hit-board --board-settings
```

`dma/run.py --dram-row-hit` selects the process-local generator and includes
the corrected command adapter, write capture and two-entry write FIFO. Synthesis
requires both passing bank proofs with current source hashes, plus the separate
strict native-adapter checks. Installed LiteDRAM sources remain unchanged.
Generated source and hash evidence are retained with each routed board.

The combined system-mul-select/row-hit route at seed 4 in
`build-ddr-dma-row-hit/board` reaches 90.17 MHz CPU / 83.47 MHz system, worse
than the prior 98.91 / 84.54 MHz candidate. Related paths are 8.79 ns and
10.01 ns (CPU-to-system), with the latter failing 10 ns. Both main clocks and
the unsupported DCI constraint diagnostic still prevent acceptance. Do not
promote this combination on functional correctness alone. The exact smoke and
stress profiles still match; see `build-ddr-dma-row-hit/ipc-comparison.json`.
