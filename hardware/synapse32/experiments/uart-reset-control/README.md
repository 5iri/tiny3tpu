# UART reset control

The integration's UART request enables originally included `!rst`. UART state
already has reset priority. This experiment supplies unmasked request enables
to that state while preserving reset gating on combinational read output and
unreset FIFO payload writes. It adds no register or acceptance cycle.

`build-uart-reset-control-proved/results.json` proves all original UART state,
FIFO payload and outputs across arbitrary bus/RX/reset inputs (483 comparison
points). Combinational event wires that intentionally differ during reset are
excluded as equivalence cutpoints, so their effects on state must be proved.
The SoC transform changes only the UART acceptance expression.

Fresh smoke and all 45 GEMM shapes preserve every PROFILE/METRICS/DMA field.
The driver `dma/run_uart_reset.py` checks proof hashes and exact parent/candidate
bytes before applying `--uart-reset-control`. The original driver is untouched.
Synthesis removes 26 LUT6 relative to UART local acceptance with no CARRY4,
register, DSP, BRAM, firmware or XDC changes.

Best tested guided seed 8: native incomplete report 82.61 MHz system / 90.32 MHz
CPU; expanded PCOUT/carry probes 11.936/11.936/12.105 ns. This improves the
preceding 12.398/12.398/12.552 ns expanded comparison. Seed 4 is worse. The
original-backend seeds report 89.03/93.41 and 88.63/83.16 MHz; coverage differs
from the guided backend, so native numbers across backends are not comparable.
No physical Fmax or 100 MHz closure is established.

Evidence: `build-ddr-{dma,gemm}-uart-reset`,
`build-ddr-seeds-uart-reset-{guided,original}-graph`, and
`build-ddr-uart-reset-{guided,original}{4,8}-timing-sensitivity`.
