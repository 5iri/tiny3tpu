# Registered forwarded operands

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

This builds on `system-mul` and shares its first system-clock register stage
across the execution unit. At CPU edge +1 it captures the selected forwarding
values. The ALU, branch/address calculations, CSR operand and divider launch
use these captured values. The multiplier computes partial products at +2 and
the final product at +3. Its separate input register is removed, so the next
CPU edge at +4 still consumes the correct product without an added stall.

Only this overlay changes operand timing. `SYSTEM_MUL=1` enables the combined
behavior; zero retains the original continuously clocked execution behavior.
The original sequencer's minimum four-system-edge CPU interval is required.
The memory sequencer samples external CPU memory outputs at +1; those outputs
are derived from the preceding CPU edge's EX/MEM registers and atomic MEM stage,
not the newly captured EX operands. PC and privilege outputs remain registered
architectural state. No clock exceptions or frequency changes are used.

In addition to checking every CPU-edge product, simulation asserts that both
captured operands equal the current unregistered forwarding outputs at **every**
enabled CPU edge. The actual candidate ALU passes 524,864 comparisons across all
instruction IDs and signed corner values at the minimum execution interval.
The existing CPU divider/interrupt/reset tests and 64-case fault/interrupt
collision matrix pass in both clock modes.

The identical MUL-heavy program still completes 4,007 instructions in 4,118 CPU
edges (0.973045 IPC), with matching complete instruction traces and every checked
MUL writeback/store. The DMA/TPU workload still passes all 35 outputs at 0.769890
IPC and 1,481,754 behavioral-model system cycles; all 162 outputs across the five
stress shapes pass too. These CPU measurements use a no-fault/no-interrupt EX
completion counter and are not precise exception-retirement measurements.

```sh
python3 hardware/synapse32/experiments/system-operands/run.py verify --out build-operands-new
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-operands-new \
  --cpu-overlay-dir build-operands-new/overlay --system-mul --dram-command-buffer
python3 hardware/synapse32/experiments/dma/run.py synth --out build-dma-operands-new \
  --cpu-overlay-dir build-operands-new/overlay --system-mul --dram-command-buffer
python3 hardware/synapse32/experiments/dma/run.py route --out build-dma-operands-new \
  --cpu-overlay-dir build-operands-new/overlay --system-mul --dram-command-buffer
```

Run the `dram-command-buffer` validation first when enabling its board option.
The behavioral CPU/DMA memory model does not include LiteDRAM frontend latency;
its counts cannot establish system-cycle changes caused by that FIFO. This is
an isolated experiment, with default RTL and board configuration unchanged.

The seed-4 route in `build-ddr-dma-system-operands/board`, including the
registered LiteDRAM command buffers, reports **67.77 MHz CPU / 60.72 MHz
system**. System-to-CPU delay is **14.09 ns** and CPU-to-system delay is
**10.94 ns**, both beyond their 10 ns budgets. This fails 100 MHz; the
unsupported `get_iobanks`/DCI constraint warning also remains unresolved.
