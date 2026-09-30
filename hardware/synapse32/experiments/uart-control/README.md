# Direct UART FIFO events

The corrected DDR design's system-clock critical path ran from reset through
UART FIFO event logic to the TX count enable (13.28 ns). The original UART
assigned temporary push/pop/clear flags with blocking assignments inside its
reset-controlled sequential process, then used them to update FIFO counts.

This candidate expresses all six events directly as combinational requests.
Actual control state retains the same asynchronous reset and update priorities.
Clear still overrides count changes; simultaneous push/pop holds the count.
TX-full rejection and RX-full simultaneous-pop acceptance are unchanged. It
inherits the proved RX/TX payload reset separation and adds no bus latency.

```sh
python3 hardware/synapse32/experiments/uart-control/prove.py --out build-ddr-uart-control
```

Temporal induction passes against the original upstream UART: all public
outputs, control registers and FIFO-owned bytes match under arbitrary bus,
serial RX and reset inputs. FIFO ring invariants are included in the proof.
Temporary event flags themselves are not architectural state.

Select `dma/run.py --uart-control` to use this generated candidate; it implies
the RX/TX payload variants. Synthesis requires the generated UART to match the
passing proof. The combined divider-payload/uart-control smoke test retains
the exact prior profile and trace hash: 173,078 instructions / 223,294 enabled
CPU edges, 0.775113 IPC and 1,185,342 system cycles, with all 35 results correct.
The combined routed board in `build-ddr-dma-control-payload/board` reaches
98.91 MHz CPU / 84.54 MHz system at seed 4, improving on 95.45 / 75.31 MHz.
It still fails both 100 MHz targets. The related CPU-to-system path is 10.08 ns
against 10 ns (system-to-CPU is 9.33 ns), and the unsupported DCI constraint
warning remains. This candidate is not timing closure or DDR hardware signoff.
