# Execution control in the existing CPU clock gaps

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

This extends `system-alu` to register the execution unit's branch, address,
exception and result outputs on the system clock. It adds no CPU stall and
does not change the memory sequencer's schedule. Forwarded operands settle at
system edge +1, non-MUL ALU results at +2, and the final control/result outputs
at +3. The earliest enabled CPU edge at +4 consumes them. MUL already has its
final register at +3, so its execution result bypasses the added register.

Interrupt priority is applied after these registers. An interrupt appearing
just before an enabled CPU edge overrides the stored control, without waiting
another system or CPU cycle. Memory/fetch fault priority remains in the CPU's
existing qualification logic. Operand outputs and CSR address/read/write ports
remain on their previous paths. `SYSTEM_MUL=0` retains continuous-clock behavior.
This overlay requires the original sequencer's minimum four-system-clock gap;
it must not be combined with a shorter-gap fetch experiment.

Validation compares every execution output with the combinational reference
for 32,768 input vectors, covering every opcode/instruction-ID combination
twice with different operands, forwarding and CSR state. Each vector is checked
after three system edges, then with a last-half-cycle interrupt asserted and
removed: 98,304 comparisons. All registered control/result outputs are also
asserted against their current combinational values at every enabled CPU edge
in the CPU and DMA/TPU tests. These are simulation checks, not a formal proof
of the entire CPU. The DIV decode register retains its induction proof.

Both continuous and gated CPU divider/reset/interrupt tests and the 64-case
fault/interrupt collision matrix pass. The multiply workload retains 4,007
instructions / 4,118 CPU edges, identical traces and 0.973045 IPC. The DMA smoke
and five-shape stress tests retain their entire profiles and cycle counts:

| Workload | Instructions | Enabled CPU edges | IPC | System cycles | Checked results |
|---|---:|---:|---:|---:|---:|
| 5×11×7 GEMM + DDR selftest | 221,485 | 287,684 | 0.769890 | 1,481,754 | 35 |
| Five GEMM shapes + DDR selftest | 463,196 | 614,386 | 0.753917 | 3,153,588 | 162 |

The counter measures EX completion on these no-fault/no-IRQ workloads, not
precise exception retirement. The behavioral memory model does not include
LiteDRAM frontend latency, arbitration or the physical DDR PHY.

```sh
python3 hardware/synapse32/experiments/system-control/run.py verify --out build-control-new
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-control-new \
  --cpu-overlay-dir build-control-new/overlay --system-mul --dram-command-buffer --bus-payload --uart-fifo
python3 hardware/synapse32/experiments/dma/run.py stress --out build-dma-control-stress-new \
  --cpu-overlay-dir build-control-new/overlay --system-mul --dram-command-buffer --bus-payload --uart-fifo
python3 hardware/synapse32/experiments/dma/run.py synth --out build-dma-control-new \
  --cpu-overlay-dir build-control-new/overlay --system-mul --dram-command-buffer --bus-payload --uart-fifo
python3 hardware/synapse32/experiments/dma/run.py route --out build-dma-control-new \
  --cpu-overlay-dir build-control-new/overlay --system-mul --dram-command-buffer --bus-payload --uart-fifo
```

Validate the optional board experiments first. Defaults remain unchanged.

The seed-4 board route in `build-ddr-dma-system-control/board` reports
**73.26 MHz CPU / 70.19 MHz system**. System-to-CPU delay improves to **10.02 ns**,
but CPU-to-system delay is **12.40 ns**. Both cross-domain paths and both main
clocks still fail their 100 MHz constraints. The unsupported `get_iobanks`/DCI
constraint diagnostic remains. This is not a timing-closed candidate.
