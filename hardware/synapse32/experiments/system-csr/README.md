# CSR execution during the existing system-clock gap

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

This extends `system-control` to capture CSR read data and address validity at
system edge +1. CSR read-modify-write results are captured at +2. The execution
unit's final result/control registers are ready by +3, before the earliest
enabled CPU edge at +4. CSR address and read enable still select the current
architectural state combinationally. Interrupt priority stays after the
execution-control registers and is not delayed.

This changes neither the CSR file nor its architectural update priority. It
requires `SYSTEM_MUL=1` and the original memory sequencer's minimum four-system
clock gap. `SYSTEM_MUL=0` retains continuous-clock operation. No added CPU
stall, custom instruction, multicycle constraint or false path is used.

At every enabled CPU edge, assertions compare the captured CSR data, validity
and write results with current combinational values. Existing operand, ALU,
execution-control and MUL assertions also remain enabled. The following pass:

- 98,304 comparisons of all execution outputs, including late IRQ assertion
  and removal; every opcode/instruction-ID pair is covered twice.
- CPU divider/reset/interrupt tests and the 64-case fault/interrupt collision
  matrix in both clock modes, plus the DIV decode induction proof.
- Identical multiply program: 4,007 instructions / 4,118 CPU edges, matching
  traces and 0.973045 IPC in both clock modes.
- DMA/TPU smoke workload: 221,485 instructions / 287,684 CPU edges, 0.769890 IPC,
  1,481,754 system cycles and all 35 signed results.
- Five DMA/TPU stress shapes: 463,196 instructions / 614,386 CPU edges,
  0.753917 IPC, 3,153,588 system cycles and all 162 signed results.

These system measurements use the behavioral DDR model; physical frontend
latency and contention are not simulated. The instruction counter is EX
completion on the no-fault/no-IRQ workloads, not precise trap retirement.

```sh
python3 hardware/synapse32/experiments/system-csr/run.py verify --out build-csr-new
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-csr-new \
  --cpu-overlay-dir build-csr-new/overlay --system-mul --dram-command-buffer \
  --bus-payload --uart-fifo --dram-write-capture
python3 hardware/synapse32/experiments/dma/run.py synth --out build-dma-csr-new \
  --cpu-overlay-dir build-csr-new/overlay --system-mul --dram-command-buffer \
  --bus-payload --uart-fifo --dram-write-capture
python3 hardware/synapse32/experiments/dma/run.py route --out build-dma-csr-new \
  --cpu-overlay-dir build-csr-new/overlay --system-mul --dram-command-buffer \
  --bus-payload --uart-fifo --dram-write-capture
```

Run the optional experiments' proofs/tests first. Default RTL, board generation
and firmware selection remain unchanged.

The seed-4 route in `build-ddr-dma-system-csr/board` reports **72.42 MHz CPU /
72.56 MHz system**. Both crossing paths pass their 10 ns budgets (system-to-CPU
9.56 ns, CPU-to-system 9.81 ns), but both main clocks still fail 100 MHz.
The unsupported `get_iobanks`/DCI constraint diagnostic also remains. This has
lower clock limits than the 84.28/73.06 MHz `dram-write-capture` parent route;
it is not promoted as an overall timing improvement.
