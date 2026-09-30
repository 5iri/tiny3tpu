# System-clock ALU result and divider decode

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

This extends `system-operands` with a register on non-MUL ALU results. Operands
settle at system edge +1, the ALU result at +2, and the enabled CPU edge at +4
consumes it. MUL keeps its existing final register at +3 and bypasses the new
register. DIV retains its original enabled-CPU-edge latency. `SYSTEM_MUL=0`
retains continuous-clock behavior; `=1` requires the original sequencer's
minimum four-system-clock interval between enabled CPU edges.

A separate DIV predicate register follows ID/EX's reset, flush, hold and stall
priority. Its equivalence to decoding the actual ID/EX outputs passes temporal
induction. Simulation checks operand freshness and ALU results at enabled CPU
edges, 524,864 ALU cases, divider/interrupt/reset behavior and the 64-case fault
collision matrix in both clock modes. The fixed multiply workload retains
4,007 instructions / 4,118 CPU edges (0.973045 IPC).

The DMA/TPU smoke test retains 221,485 instructions / 287,684 CPU edges
(0.769890 IPC), 1,481,754 system cycles and all 35 signed results. Five stress
shapes retain their complete instruction profile, cycle counts and 162 results.
These use the behavioral DDR model; they do not measure physical LiteDRAM
latency or contention. The EX completion counter is used only without faults
or interrupts and is not a precise exception-retirement counter.

The seed-4 board route in `build-ddr-dma-system-alu/board` includes the DMA,
registered LiteDRAM command buffers, `bus-payload` and `uart-fifo`. It reports
**73.70 MHz CPU / 70.22 MHz system**. System-to-CPU delay is **13.70 ns**, and
CPU-to-system delay is **9.38 ns**, against 10 ns budgets. This fails 100 MHz.
The unsupported `get_iobanks`/DCI constraint warning also remains unresolved.
No timing exceptions, bitstream generation, FPGA programming or default
configuration promotion are part of this experiment.

```sh
python3 hardware/synapse32/experiments/system-alu/run.py verify --out build-alu-new
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-alu-new \
  --cpu-overlay-dir build-alu-new/overlay --system-mul --dram-command-buffer --bus-payload --uart-fifo
python3 hardware/synapse32/experiments/dma/run.py synth --out build-dma-alu-new \
  --cpu-overlay-dir build-alu-new/overlay --system-mul --dram-command-buffer --bus-payload --uart-fifo
python3 hardware/synapse32/experiments/dma/run.py route --out build-dma-alu-new \
  --cpu-overlay-dir build-alu-new/overlay --system-mul --dram-command-buffer --bus-payload --uart-fifo
```

Run the three optional experiments' validation commands first. The DMA runner
requires their passing evidence before board synthesis.
