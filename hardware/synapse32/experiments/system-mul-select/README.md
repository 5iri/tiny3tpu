# Direct final multiply-result selection

The system-control pipeline bypassed its final EX register for every instruction
ID classified as MUL, selecting the full combinational EX result. That retained
an unnecessary path through unrelated opcode/CSR result selection. The routed
CPU critical path reached EX/MEM from CSR address decode.

This candidate selects the final multiply register directly for MUL IDs with
R/I ALU opcodes. Other results use the settled EX register. Continuous-clock
mode retains the original combinational result. The outer late-interrupt
priority remains unchanged. No enabled CPU cycles or firmware changes are added.

The narrower bypass also preserves behavior for arbitrary mismatched opcode and
instruction-ID inputs: 98,304 comparisons against the original EX unit pass,
including late IRQ assertion/removal. CPU tests and the 64-case fault/interrupt
matrix pass in continuous and gated modes, and the fixed benchmark retains
identical traces and 4,007 / 4,118 (0.973045 IPC).

```sh
python3 hardware/synapse32/experiments/system-mul-select/run.py verify --out build-ddr-system-mul-select
```

The overlay inherits divider-payload and system-decode. The combined DMA smoke
test also retains 173,078 / 223,294 (0.775113 IPC), 1,185,342 system cycles and
all 35 expected results. Board timing remains a separate acceptance check.
