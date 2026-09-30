# Shared combinational multiplier

This overlay builds on forwarding retiming and the iterative divider. One
signed 33×33 product replaces three independent signed/mixed/unsigned products.
The operand extension bits select MULH/MULHSU signedness. MUL uses the low word;
the high variants use bits 63:32. CPU instruction latency and stalls are unchanged.

Validation in `build-ddr-shared-mul` includes 524,864 ALU comparisons against the
original ALU, CPU divider/interrupt/fault cases, and the CPU/DDR-model/TPU workload.
The fixed MUL workload completes the same 4,007 instructions in 4,118 enabled
CPU edges (0.973045 IPC), with identical completion traces in both clock modes.
The full board uses 36 DSPs: four CPU DSPs and 32 in the two TPU cores.

Seed-4 routing reaches 47.92 MHz CPU and 62.59 MHz system. Both 100 MHz targets
fail. The unsupported DDR DCI constraint warning remains. This is an isolated
experiment, with no default RTL promotion or FPGA programming.

```sh
python3 hardware/synapse32/experiments/shared-mul/run.py verify --out build-shared-new
python3 hardware/synapse32/experiments/shared-mul/run.py synth --out build-shared-new
python3 hardware/synapse32/experiments/shared-mul/run.py route --out build-shared-new
```

Use a fresh output directory to preserve previous evidence. The route command
returns failure when timing acceptance fails, even if nextpnr completed routing.
