# Decode and register-file reads in existing clock gaps

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

This extends `system-csr`. After an enabled CPU edge updates IF/ID, decoded
register addresses, valid bits, immediate, opcode and instruction ID are
captured on system edge +1. Register-file read values are captured at +2.
ID/EX consumes the settled values at the next enabled CPU edge, no earlier
than +4. The CPU pipeline has the same number of enabled edges and stalls.

The register-file implementation, write-through logic and write clock are
unchanged. Hazard and forwarding lookahead logic use the captured decode
outputs, which settle before the next enabled CPU edge. Reset, flush and hold
priority remain in the original pipeline stages. `SYSTEM_MUL=0` bypasses these
new registers for continuous-clock operation; `=1` requires the original
four-system-clock minimum CPU interval.

Simulation asserts every captured decode and register-file output against
its current combinational source at each enabled CPU edge. All inherited EX,
CSR, operand and multiply checks remain enabled. Divider/reset/interrupt tests
and the 64-case fault/interrupt matrix pass in both clock modes. The multiply
program retains identical traces and 4,007 instructions / 4,118 CPU edges
(0.973045 IPC).

DMA/TPU tests retain the full reference profiles: 221,485 instructions /
287,684 CPU edges, 0.769890 IPC and 1,481,754 system cycles for the 35-result
smoke workload; 463,196 / 614,386, 0.753917 IPC and 3,153,588 cycles for all 162
stress results. These counts use the behavioral DDR model and no-fault/no-IRQ
EX completion measurement, not physical DDR contention or trap retirement.

```sh
python3 hardware/synapse32/experiments/system-decode/run.py verify --out build-decode-new
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-decode-new \
  --cpu-overlay-dir build-decode-new/overlay --system-mul --dram-command-buffer \
  --bus-payload --uart-rx-fifo --dram-write-capture
python3 hardware/synapse32/experiments/dma/run.py synth --out build-dma-decode-new \
  --cpu-overlay-dir build-decode-new/overlay --system-mul --dram-command-buffer \
  --bus-payload --uart-rx-fifo --dram-write-capture
python3 hardware/synapse32/experiments/dma/run.py route --out build-dma-decode-new \
  --cpu-overlay-dir build-decode-new/overlay --system-mul --dram-command-buffer \
  --bus-payload --uart-rx-fifo --dram-write-capture
```

Validate the optional peripheral and DDR changes first. No default changes or
FPGA programming are performed.
