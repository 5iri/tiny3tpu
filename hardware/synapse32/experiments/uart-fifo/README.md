# Remove reset from invalid UART TX data

The FIFO's data write uses the existing bus write condition in its own clocked
block. Reset still clears its ownership state, head, tail and count. A bus
write during reset may change an unowned data byte; no valid FIFO entry depends
on it, and the next accepted write overwrites the byte before it becomes valid.
This removes reset from the TX data-memory write enable and allows RAM mapping.

Temporal induction compares the original and candidate UART outputs, all
control state, RX storage and every owned TX byte under arbitrary bus, RX and
reset inputs. The proof includes the FIFO head/count/tail ring invariant.

```sh
python3 hardware/synapse32/experiments/uart-fifo/prove.py --out build-ddr-uart-fifo
```

Enable with `dma/run.py --uart-fifo`; board synthesis requires the exact source
hash to match the passing proof. The combined `system-alu` CPU/DMA/TPU tests
retain their complete profiles and cycle counts. The combined route is
documented there; no independent UART-only Fmax improvement is claimed.
