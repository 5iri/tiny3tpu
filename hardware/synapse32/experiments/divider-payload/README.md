# Divider working-data ownership

The corrected DDR design's CPU critical path ran from privilege/trap control
through divider launch/cancel logic to the dividend register enable (10.48 ns).
This experiment builds on system-decode and removes start/cancel/reset gating
from the divider's internal working data. Busy, done, iteration count and the
architectural result retain their original control and reset behavior.

While idle, the working registers capture potential operands and initialize
quotient/remainder on every enabled CPU edge. An accepted ordinary launch
therefore initializes all working data at the same edge as the original. While
busy, each edge computes the original division step. Cancel releases ownership;
any concurrent working-data update is unobservable. Special-case results still
use the original live inputs and completion logic. No CPU edge is added or
removed, and the ISA is unchanged. Extra idle data switching is possible;
power has not been measured.

```sh
python3 hardware/synapse32/experiments/divider-payload/run.py verify --out build-ddr-divider-payload
```

Temporal induction proves identical busy/done/result/count and identical
busy-owned working data against the original divider, with arbitrary operands,
start, cancel, reset and modes. The arithmetic test passes 16,437 cases,
including cancellation at 33 boundaries, destroyed live inputs after launch
and exact completion latency. CPU verification also exercises continuous and
gated clocks, interrupt/fault collisions and the fixed IPC benchmark.

The combined UART-control smoke test retains the exact previous instruction
profile, trace hash, DMA counts and system cycles. The DDR behavioral model
does not instantiate the native adapter; its separate strict-deadline adapter
proofs/tests remain required for board synthesis. Physical timing is a separate
acceptance criterion, with both 100 MHz clocks and related-clock paths checked.

Both CPU clock modes pass the 64-case fault/interrupt collision matrix and
retain 4,007 / 4,118 (0.973045 IPC) with identical fixed-benchmark traces.
The combined firmware stress test also retains 306,842 / 405,428 (0.756835 IPC)
and 2,189,877 system cycles, with all 162 results correct. Exact smoke/stress
comparisons are saved in `build-ddr-dma-control-payload/ipc-comparison.json`.
