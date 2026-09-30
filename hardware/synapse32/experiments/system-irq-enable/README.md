# Interrupt eligibility in the system-clock gap

This candidate builds on system-mul-select. It computes six eligibility bits
from MSTATUS, MIE, MIDELEG and current privilege, then captures those bits on the
system clock. CSR state changes at enabled CPU edges, leaving the existing gap
for this calculation. The pending MIP bits remain live and are not registered
here, so external, software and timer events can still arrive immediately before
an enabled CPU edge. Machine/supervisor and cause priorities remain unchanged.

Continuous-clock mode bypasses the eligibility registers. Gated mode asserts
at every enabled CPU edge that its captured eligibility equals the current raw
expression. Reset and the original minimum four-system-clock CPU interval are
retained; this adds no enabled CPU stalls.

```sh
python3 hardware/synapse32/experiments/system-irq-enable/run.py verify --out build-ddr-system-irq-enable
```

All 524,288 combinations of relevant enable/delegation/global/privilege settings
and pending causes compare against upstream in both modes. Pending bits and PC
change between clock edges. CPU divider/interrupt tests, the 64-case fault/IRQ
collision matrix in both modes, and the fixed multiply benchmark pass. The
benchmark retains identical traces and 4,007 / 4,118 (0.973045 IPC).

The complete DMA smoke and stress tests also retain their exact instruction
profiles, traces, DMA counts and system cycles: 0.775113 and 0.756835 IPC, with
all 35 and 162 results correct. Routing must establish whether this improves
the physical interrupt/flush path; correctness alone is not acceptance.
