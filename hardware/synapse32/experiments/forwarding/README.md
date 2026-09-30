# Isolated forwarding / execution-result candidate

Parent full-board follow-up: [BOARD_RESULTS.md](BOARD_RESULTS.md) records
41.99 MHz CPU / 48.02 MHz system, both failing 100 MHz. The small CPU gain comes
with a substantial system regression; this remains an isolated experiment.
The sections below describe the worker's earlier proof/simulation/synthesis
handoff, before the parent physical run.

The candidate is functionally equivalent to the divider baseline at the
execution-unit boundary. CPU simulation passes. XC7 resource results are mixed;
**no timing improvement or 100 MHz capability has been established**. No
full-board synthesis, placement, routing, bitstream generation or programming
was run for this candidate.

Only this directory was modified. The sibling Synapse32 tree, divider overlay,
other experiments and existing board build are read-only inputs.

## Overlay contract

Replace `experiments/divider/execution_unit.v` with this directory's
`execution_unit.v` in the CPU source list. Keep the divider's `riscv_cpu.v`,
`alu.v`, `divider.v`, and the original sibling `csr_exec.v`. Compile exactly one
execution unit. `overlay.json` records this mapping; it is descriptive metadata,
not an existing board-tool configuration option. This is an incremental overlay,
not a complete four-file `CPU_OVERLAY_DIR` for the parent's CMake runner.

To create a builder-compatible four-file overlay without editing the shared
builder or divider, run from the repository root:

```sh
python3 hardware/synapse32/experiments/forwarding/make_overlay.py
```

The command prints a fresh absolute `forwarding/overlay.*` directory. Pass that
path as the parent's existing `CPU_OVERLAY_DIR` (or equivalent board-builder
overlay argument). It contains byte-for-byte divider copies of `riscv_cpu.v`,
`alu.v`, `divider.v`, plus this candidate's `execution_unit.v`. It verifies all
four inputs against the successful proof/test/synthesis manifests before copying
and writes `manifest.json` with source paths and hashes. It creates no files
outside this experiment and does not launch the parent build.

The baseline CPU source set was checked against `build-ddr-divider/synth.ys`.
Use the same Slang options and include path as that build. Do not define
`FORMAL`: the divider ALU retains a pre-existing simplified branch under that
macro. Preserve board constraints, clocks, seed, frequency target and timing
checks for any separately authorized physical comparison.

## Bounded RTL change

* Replace both forwarding data `case` muxes with mutually exclusive masks and
  ORs. Codes 01/10 select MEM/WB; both 00 and 11 retain the register-file value.
  The forwarding producer, MEM-over-WB priority, load/AMO exclusions and x0
  handling are unchanged.
* Replace assignments to the wide execution result inside nested control logic
  with one-bit enables at the identical assignment sites. A parallel masked mux
  selects ALU, link PC+4, immediate, PC+immediate or CSR data. Interrupt/invalid
  suppression and CSR exception conditions retain their original priority.
  JAL/JALR still produce a link value on misalignment, matching the baseline.

No ports were added, no pipeline registers or stages changed, and no ISA or
latency change was made relative to the divider baseline. This is an RTL
structure experiment; the mapper can restructure these expressions.

## Reproduce and inspect

From the repository root:

```sh
python3 hardware/synapse32/experiments/forwarding/run.py prove
python3 hardware/synapse32/experiments/forwarding/run.py test
python3 hardware/synapse32/experiments/forwarding/run.py synth
python3 hardware/synapse32/experiments/forwarding/collision.py
diff -u hardware/synapse32/experiments/divider/execution_unit.v \
        hardware/synapse32/experiments/forwarding/execution_unit.v
```

`SYNAPSE32_SOURCE` overrides the sibling path; `YOSYS` overrides the default
OSS CAD Suite executable. Yosys must provide Slang. Verilator is found through
PATH. Builds use at most two compilation jobs; all artifacts stay under this
directory. Each successful mode writes a compact `evidence/<mode>.json` with
tool versions, absolute raw-log directory, SHA-256 input manifest and results.
Sources are hashed again after each mode to check they were unchanged during
the run. Generated build directories are ignored by Git; compact evidence is not.

## Equivalence evidence

Yosys 0.63+173 (`66306a8ca-dirty`) with Slang elaborates the baseline and
candidate execution units separately, including the full divider ALU and
original CSR execution module. It flattens and optimizes each, checks hierarchy
and combinational loops, then uses `equiv_make`, `equiv_simple` and
`equiv_status -assert`. All **1,292 equivalence cells proved; zero unproven**.

All execution-unit outputs and matched internal wires are checked. Inputs are
unrestricted two-state values, including inconsistent opcode/instruction IDs,
invalid instructions, all forwarding codes, interrupt/privilege controls and
arbitrary divider results. There are no assumptions, blackboxes, or ALU-output
substitutions. Both elaborations assert the presence of all three `$mul` cells
to catch accidentally selecting the simplified ALU branch. Matching internal
wires are proof cut points whose equivalence is also discharged.

This is combinational replacement equivalence, not a whole-CPU sequential
formal run or four-state X-propagation equivalence. The unchanged sequential
logic is exercised by actual CPU simulation below.

## Functional evidence

The unchanged divider `cpu_tb.sv` was run against both source sets with
Verilator 5.046, in continuous-clock and board-sequencer/gated-clock modes.
All four runs passed, and the runner checks exact agreement of their PASS
records for each clock mode:

| Per run | Baseline and candidate |
| --- | ---: |
| Program words | 3,960 |
| Divides / divide retirements / divide writebacks | 1,067 each |
| Launches, including canceled interrupt/retry | 1,068 |
| Checked, ordered stores / data reads | 1,355 / 1 |
| Interrupt/retry | 1 |
| CPU edges | 35,213 |
| System cycles, continuous / gated | 35,213 / 318,748 |

Tests exercise MEM/WB dependencies, dependent ADD/store/branch, load-use,
back-to-back divides, operand/destination alias, x0, wrong-path squashing,
reset during division, and CSR-enabled interrupt/MRET cancellation and retry.
The gated target applies request backpressure and variable response delays.
The parent's new `cpu_collision_tb.sv` also passed with the candidate:
64 cases in each clock mode, **128 total**, with 24 interrupt-boundary and
40 fault-priority cases per mode and 256 checked stores per mode. This covers
external instruction/load page-fault inputs, interrupt collisions and division
launch/final-iteration/consumption boundaries. Exact records and source hashes
are in `evidence/collision.json`. The actual MMU page walker, complete upstream
ISA suite and physical DDR were not run. Verilator builds use `-Wno-fatal`;
their warning logs are retained.

The prepared handoff overlay is `overlay.iqat1u1i/`; its `manifest.json` records
all four copied inputs. A new one can be created with `make_overlay.py`.

## Synthesis evidence and limits

Both CPU-only runs use `synth_xilinx -family xc7 -top riscv_cpu -noiopad
-noclkbuf`, identical tool/options and original CSR. Both pass hierarchy checks,
pre/post mapping `check -assert`, zero pre-mapping SCCs, and absence of
combinational divide/modulo operators.

| Mapped resource | Divider baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| LUT1–LUT6 | 5,155 | 5,144 | -11 |
| CARRY4 | 207 | 205 | -2 |
| MUXF7 | 214 | 301 | +87 |
| MUXF8 | 48 | 55 | +7 |
| Flip-flops | 2,316 | 2,316 | 0 |
| DSP48E1 | 12 | 12 | 0 |
| Total cells | 8,061 | 8,137 | +76 |

The small LUT reduction comes with increased dedicated mux usage and total
cells. These counts do not establish reduced path delay, routing fanout or
application speedup, and are not sufficient to promote this over the baseline.

The existing divider board report at `build-ddr-divider/route.log:1788` reports
the rs1-valid-to-EX/MEM path as 23.9 ns (3.1 ns logic, 20.8 ns routing).
Line 1946 reports CPU 41.81 MHz, failing its 100 MHz target. Those are baseline
measurements, not candidate measurements. The requested seed-4 physical setup
has not been rerun. A future authorized physical A/B comparison must measure
whether this candidate helps that routing-dominated path.
