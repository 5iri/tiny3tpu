# Execution-result selection experiment

Starting with `shared-mul`, this overlay expresses execution-result selection
as parallel, mutually exclusive opcode predicates and a masked OR. Other
execution outputs and instruction scheduling are unchanged.

`prove` checks every execution-unit output against the original, using a common
arbitrary ALU result and the real CSR execution logic. `verify` adds the CPU
divider/interrupt/fault tests, DDR-model/TPU workload and fixed-program IPC check.
All pass in `build-ddr-result-select`; instruction traces and 0.973045 CPU IPC
match the shared multiplier baseline.

Seed-4 full-board routing is 46.90 MHz CPU / 73.22 MHz system, versus 47.92 /
62.59 for the shared multiplier. The CPU result regresses slightly and neither
target reaches 100 MHz. The unsupported DCI warning remains. This experiment
has not been selected for the DMA integration or promoted to default RTL.

```sh
python3 hardware/synapse32/experiments/result-select/run.py verify --out build-select-new
python3 hardware/synapse32/experiments/result-select/run.py synth --out build-select-new
python3 hardware/synapse32/experiments/result-select/run.py route --out build-select-new
```
