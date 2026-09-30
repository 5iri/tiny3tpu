# RX and TX FIFO payload reset separation

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

This extends `uart-fifo` to RX storage. The RX write condition still requires
RX_STOP, an expired baud counter, a high stop bit, no FIFO clear, and either
space or a simultaneous successful pop. Head, tail, count, overrun status and
all UART control retain their original reset and update priorities.

Payload capture runs outside the reset-controlled block. A coincident reset
and receive completion may write an unowned byte, but reset empties the FIFO.
Every byte is overwritten by an accepted receive operation before becoming
owned. The proof compares all public outputs, control state and owned bytes
of both FIFOs, including full-FIFO simultaneous pop/push and arbitrary resets.
Both ring invariants are included in the induction property.

```sh
python3 hardware/synapse32/experiments/uart-rx-fifo/prove.py --out build-ddr-uart-rx-fifo
```

Temporal induction passes. Enable `dma/run.py --uart-rx-fifo`; this includes the
TX change and requires an exact candidate match to the passing proof before
synthesis. The CPU/DDR-model/TPU smoke test retains all 35 results, 0.769890 IPC
and 1,481,754 system cycles. This is an opt-in generated UART; defaults are
unchanged.
