# Registered forwarding-control experiment

The experiment is implemented and functionally checked, but **does not close
100 MHz timing**. Production RTL and the default build selection are unchanged.

`run.py` materializes a four-file CPU overlay from the divider experiment. It
replaces the combinational forwarding selector with the existing look-ahead
control prototype, embedded in `riscv_cpu.v`. The execution unit, ALU, divider,
five pipeline stages, instruction latency, clocks, firmware and board RTL are
unchanged relative to the divider baseline. Selectors update during holds because
MEM/WB continue advancing. A simulation-only monitor compares them with the
original forwarding unit on each tested falling CPU edge.

## Which baseline is being compared?

The newest saved board route preceding this experiment is
`build-ddr-forwarding/route.log`. Its approximately 49 MHz result is **48.02 MHz
on system clock `clk`**; its CPU clock is **41.99 MHz**. There is no exact 49 MHz
final Fmax result in the searched local reports. These are different clock domains
and must not be compared interchangeably.

| Final routed Fmax | Divider baseline | Prior forwarding rewrite | This experiment |
| --- | ---: | ---: | ---: |
| CPU `soc.cpu_clk`, target 100 MHz | 41.81 MHz | 41.99 MHz | 45.62 MHz |
| System `clk`, target 100 MHz | 61.02 MHz | 48.02 MHz | 62.48 MHz |

Evidence is in `build-ddr-divider/route.log`,
`build-ddr-forwarding/route.log` and `build-ddr-retime/board/route.log`.
The prior forwarding rewrite changes `execution_unit.v`; this experiment starts
from the divider version instead. Consequently the direct controlled comparison
for the new registers is the divider column. All three use seed 4, nextpnr
52d3cc8 and the same chip database. The experiment's XDC and firmware HEX are
byte-for-byte equal to the divider baseline. Its tool, chip database, netlist,
firmware and XDC hashes are in `build-ddr-retime/board/route-manifest.json`.
The tool hash matches the earlier recorded executable. Recorded existing input
hashes in the pipeline-plan and combined experiments were also checked against
current files: all 23 and 55 entries, respectively, still matched.

The default `tools/kc705_open_build.py` command selects the sibling CPU sources.
The divider and forwarding builds require explicit `--cpu-overlay-dir` selections;
they have not been promoted into that default source tree. Build-directory names
alone therefore do not identify the source configuration.

## Verification and remaining bottlenecks

- Dynamic control test: 30,775 post-edge selector comparisons passed.
- `prove.py`: Yosys temporal induction proved selector equality against the
  actual ID_EX, EX_MEM, MEM_WB and forwarding-unit RTL, with unrestricted input
  tags, instruction IDs, reset, holds, flushes and faults. This proves the
  embedded helper's control invariant, not whole-CPU ISA equivalence.
- Actual CPU tests, continuous and sequencer-gated: each passed 1,067 divides,
  1,355 ordered stores, and 35,213 enabled CPU edges, with the forwarding monitor
  enabled. System cycles were 35,213 and 318,748 respectively.
- Interrupt/fault collision tests: 64 cases in each clock mode, all passed.
- Actual CPU with variable-latency DDR memory model and TPU: all 35 signed
  results passed in 4,981,249 system cycles, with 9,294 external reads and 8,400
  writes. All emitted workload metrics match the recorded divider baseline.
- Full board synthesis passed structural checks. Physical routing completed;
  the acceptance check correctly returned failure for both 100 MHz targets.

The new CPU worst path is 21.9 ns: EX/MEM instruction ID through SC-result
selection and forwarded operand data into the unregistered multiplier, ending
at EX/MEM execution-result bit 10. The path explicitly includes
`alu_inst.mul_signed[10]`. Its breakdown is 7.8 ns logic and 14.1 ns routing.
The separate system path remains 16.0 ns, starting at sequencer state and
passing through request-address and peripheral-control logic (2.2 ns logic,
13.8 ns routing). Forwarding-control retiming alone is insufficient. Further
CPU work must shorten the multiply/operand path while preserving measured CPU
IPC; inserting a globally stalling multiplication boundary fails that criterion.
The system path also needs its own decode/control work. Those changes are not
implemented by this experiment.

These are single-seed diagnostic measurements, not a general timing or throughput
claim. The original unsupported `get_iobanks`/DCI constraint diagnostic remains.
No bitstream was produced or programmed, and DDR electrical timing, calibration,
clock-enable timing and hardware operation have not been established.

## Reproduce

From the repository root, with the same tools and sibling CPU checkout:

```sh
python3 hardware/synapse32/experiments/forward-retime/run.py verify --out build-ddr-retime
python3 hardware/synapse32/experiments/forward-retime/prove.py --out build-ddr-retime
python3 hardware/synapse32/experiments/forward-retime/run.py synth --out build-ddr-retime
python3 hardware/synapse32/experiments/forward-retime/run.py route --out build-ddr-retime
```

Use a new `--out` directory to preserve existing evidence. The route command
returns exit code 1 when its completed report fails acceptance; nextpnr's own
zero exit code does not establish timing closure.
