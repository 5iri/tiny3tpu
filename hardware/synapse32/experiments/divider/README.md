# Isolated multi-cycle divider integration candidate

Implemented and simulation/synthesis checked; **physical timing and board
validation are incomplete**. No route, bitstream, FPGA programming, frequency
change, false path, or instruction subset restriction was used. All created
files and generated builds are under this directory. The upstream Synapse32
tree and sibling experiments were read only.

The baseline parent's diagnostic is 159.0 ns / 6.29 MHz, with the dominant
path through the ALU's combinational divide/modulo implementation (see
../cpu/README.md). This candidate removes those operators from the synthesized
CPU. It does not establish a new maximum frequency or application speedup.

## Parent integration contract

Replace these four source-list entries as a group; do not compile both versions:

| Read-only upstream source, relative to Synapse32 | Overlay here |
| --- | --- |
| rtl/riscv_cpu.v | riscv_cpu.v |
| rtl/execution_unit.v | execution_unit.v |
| rtl/core_modules/alu.v | alu.v |
| rtl/core_modules/divider.v | divider.v |

The CPU's external ports are unchanged. Execution/ALU acquire a div_result
input; divider acquires synchronous cancel. These internal modules are not
individually drop-in replacements. integration.patch is a reviewable diff
against the captured source, **not an instruction to modify the upstream tree**.
SOURCE_SHA256.txt records all CPU inputs, include files, tested board blocks,
and the optional CSR overlay. Four overlaid upstream files were additionally
compared byte-for-byte with their initial snapshots after implementation.

Use the parent's existing Slang invocation, including
--allow-use-before-declare --single-unit --top riscv_cpu, include path, and
split CPU/board frontend. Retain the full production ALU path: do not define
FORMAL (the upstream ALU contains a pre-existing simplified FORMAL branch).
Preserve the original clock/reset, sequencer, BUFGCE, frequency, XDC, DDR,
chip database, seed and timing checks. SYNAPSE32_CLOCK_SIM is test-only.

Combination A is these four overlays with original csr_exec.v.
Combination B additionally substitutes ../cpu/csr_exec.v. Both passed the
same actual-CPU tests and independent XC7 synthesis. The CSR combination
must still win a parent physical A/B comparison; no other sibling candidate
was combined or edited. Overlapping CPU/ALU/execution changes from another
track need an explicit merge and rerun of these tests.

## Pipeline and memory behavior

* DIV/DIVU/REM/REMU are recognized only for a valid EX instruction. At launch
  the divider captures both operands after the existing MEM/WB forwarding
  muxes, plus signed/remainder mode. Operand changes as older instructions
  drain cannot alter the operation.
* Until done, PC and IF/ID stall and ID/EX holds. Every waiting edge flushes
  EX/MEM to a bubble while MEM/WB and the register file continue advancing.
  This drains each older memory request once and preserves younger decode
  operands through the register file's existing write-through path.
* The done cycle admits exactly one divide result into EX/MEM and increments
  instret once. The following instruction uses ordinary MEM/WB forwarding,
  including another divide or a dependent store/branch. rd=x0 still executes.
* Reset clears the divider. Pipeline flush has priority over start/iteration/
  completion and clears busy/done synchronously. Interrupts retain the existing
  precise EX resume-PC behavior: the canceled instruction is retried after
  MRET. Launch is suppressed on flush. Existing page-fault redirects also
  drive cancellation. Directed external instruction/load page-fault collisions
  at launch are tested below; address translation itself is not modeled.
* Normal division requires a launch edge, 32 iteration edges, then a consume
  edge: 33 extra EX stall edges compared with the original single-cycle ALU.
  Divide-by-zero and signed INT_MIN/-1 produce done at launch and consume at
  the next edge: one extra stall. Signed results truncate toward zero and
  remainder follows the dividend sign. Zero divisors return all-one quotient
  or the original dividend remainder; signed overflow returns INT_MIN or zero.
* Divider progress uses the existing CPU clock exclusively. The board's
  sequencer continues its full data/fetch/step/settle protocol for every
  enabled edge; there is no added clock or bypass. EX/MEM bubbling prevents
  repeated loads/stores during those progress edges. Do not hold EX/MEM or
  freeze the entire CPU around this divider: the sequencer would resample
  a held request or the divider would stop progressing.

The unchanged sequencer means repeated fetches of the held PC and potentially
large wall-time divide latency. The final iteration also includes sign
correction. These remain performance costs for the parent to measure.

## Reproduce

Run from any directory:

```sh
bash /Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/divider/verify.sh
bash /Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/divider/synthesize.sh
CSR_OVERLAY=/Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/cpu/csr_exec.v \
  bash /Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/divider/verify.sh
CSR_OVERLAY=/Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/cpu/csr_exec.v \
  bash /Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/divider/synthesize.sh
```

SYNAPSE32_SOURCE and YOSYS can override local tool/source defaults.
Build jobs are capped at two. Unique build.*/synth.* directories stay here
and are ignored by Git; compact retained logs are under evidence/.

## Test results

Icarus 13.0: divider_tb.sv passed **16,437 arithmetic operations**, covering
4,096 deterministic random operand pairs in all four modes, directed zero/
overflow cases, and retries after cancellation. It checks captured operands,
exact normal/special latency, stable results, one-shot completion, and cancel
at 33 iteration/completion boundaries.

Verilator 5.046: cpu_tb.sv executes real RV32 machine instructions through
the actual CPU, decoder, register file, forwarding, CSR and pipeline modules.
It does not replace the CPU with a transaction driver or force internal state.
The 3,960-word program covers the 12x12 corner operand cross-product in all
four operations, 200 random divisions, independent/dependent back-to-back
divides, WB/MEM operand forwarding, load-use stalls, source/destination alias,
x0, dependent ADD/store/branch, wrong-path divide/store squashing, reset during
division, and a real CSR-enabled timer interrupt followed by MRET/retry.

Each CPU run passes:

| Check | Result |
| --- | ---: |
| Architectural divisions / divide retirement / divide WB events | 1,067 each |
| Launches (one canceled, retried interrupt) | 1,068 |
| Accepted, ordered, value-checked stores to one MMIO-like address | 1,355 |
| Data reads | exactly 1 |
| Interrupt canceled and correctly resumed | 1 |
| CPU edges, including final observation period | 35,213 |
| System cycles, continuous-clock test | 35,213 |
| System cycles, board sequencer/clock-enable test | 318,748 |

The gated test instantiates the unchanged board memory sequencer and
falling-edge-latched BUFGCE simulation model at a 100 MHz system clock.
The memory target applies request backpressure and 1–7-cycle response delays;
accepted writes are checked individually, so duplicate side effects cannot
hide behind idempotent final RAM contents. Both combinations passed both
clock modes. Test logs: evidence/divider.log and evidence/divider-csr.log.

These are dynamic tests, not an exhaustive sequential equivalence proof.
Physical DDR, asynchronous clock-buffer timing, full MMU translation, atomics mixed with
division, and the complete upstream ISA suite remain unvalidated here.

## Directed CPU interrupt/flush boundary regression

Added cpu_collision_tb.sv and included it in verify.sh for both clock modes.
This follow-up changes only that new test, verify.sh and this README.
The divider/CPU/ALU/execution overlays and BOARD_RESULTS.md are unchanged.
No synthesis or board build was run for this follow-up.

The test executes real CSR setup, DIV/DIVU/REM/REMU, memory operations, and MRET.
It drives only external timer-interrupt and instruction/load page-fault inputs.
Internal hierarchy is observed to prove the collision edge; there are no
forces, deposits, or replacement CPU/pipeline models.

Each clock mode runs the following **64 independently reset cases**:

| External event and operand class | Operations | Collision edges | Cases |
| --- | --- | --- | ---: |
| Timer interrupt, normal operands 0xffffff9b / 7 | All four | Launch, final iteration, consume | 12 |
| Timer interrupt, zero divisor (dividend 0xffffff9b) | All four | Launch, consume | 8 |
| Timer interrupt, signed overflow INT_MIN / -1 | DIV, REM | Launch, consume | 4 |
| Instruction page fault only | All ten operation/operand combinations above | Launch | 10 |
| Older independent load page fault only | Same ten | Launch | 10 |
| Instruction page fault plus pending timer interrupt | Same ten | Launch | 10 |
| Older load page fault plus pending timer interrupt | Same ten | Launch | 10 |

The 24 interrupt cases per mode all exercise interrupt-induced pipeline flush.
The other 40 exercise synchronous flush, including 20 simultaneous fault/IRQ
priority cases. Fast paths have no iteration edges, so no final-iteration case
is claimed for them. New instruction/load faults at final iteration or consume
are not injected: instruction-fault metadata is already held in ID/EX, and
older MEM entries have drained. Artificially forcing those internal states
would not represent this CPU interface. Store-page-fault, reset-at-boundary,
and simultaneous instruction-plus-data-fault priority cases are not added here.

The interrupt is scheduled one **enabled CPU edge** before the desired trap
edge because mip registers the external input. At the actual trap edge the
test asserts launch suppression (!busy, !done, !start), or busy with count_q=31
for final iteration, or !busy with done for consume. It checks pending IRQ
presence in each combined fault case and verifies the synchronous fault wins.

Every case checks flush, no divide retirement on the canceled edge, unchanged
instret counter on that edge, cleared divider busy/done and ID/EX/EX/MEM
valid state after the edge, mtvec redirect, exact mcause, and exact mepc.
MRET must retry the target divide (or the older faulting load followed by the
divide). The completed divide must have exactly one retirement and one checked
writeback. Launch collisions permit only the retry launch; final/consume
collisions require two launches total. Architectural destination, dependent
ADDI result and older-load register values are also checked.

Every case emits four ordered, individually value-checked stores to one
MMIO-like address: an older marker, the divide result, its dependent ADDI
result, and a completion marker. Fifty additional enabled edges after the
last store detect delayed duplicates/stale work. A faulting load is expected
to be requested again on retry (two reads); all other cases require one read.
The gated model retains request backpressure and 1–7-cycle response delays.
These are CPU fault-input tests, not physical MMU or DDR validation.

Executed successfully with bash verify.sh:

* **128/128 new CPU collision cases** across the two clock modes: 48 timer
  boundary cases and 80 synchronous-fault cases, including 40 fault/IRQ
  priority collisions; exactly 512 accepted stores across the new matrix.
* Existing standalone suite: **16,437** arithmetic checks and **33** cancel
  boundaries, passed.
* Existing broad CPU suite: **1,067** divide retirements/writebacks and exactly
  **1,355** stores in each clock mode, passed.

Raw evidence from this follow-up is build.y84pyo/: collision0.log,
collision1.log, run0.log, run1.log and divider.log, with matching compile logs.
Each collision log reports shape (0 normal, 1 zero divisor, 2 signed overflow),
op (4 DIV, 5 DIVU, 6 REM, 7 REMU), phase (0 launch, 1 final iteration, 2 consume),
source (0 IRQ, 1 instruction fault, 2 load fault, 3 instruction fault + IRQ,
4 load fault + IRQ), and observed event counts. This run uses the default
original CSR implementation; the new matrix was not rerun with CSR_OVERLAY.

## Synthesis evidence

Yosys 0.63+173, 66306a8ca-dirty, production Slang frontend. Both combinations
pass hierarchy -check, check -assert before/after mapping, zero combinational
SCCs, and an assertion that no $div/$mod/$divfloor/$modfloor cells remain.
XC7 CPU-only mapping uses synth_xilinx -family xc7 -noiopad -noclkbuf.
It is a structural/resource check, not whole-board timing signoff.

| CPU-only mapped resources | Divider | Divider + CSR |
| --- | ---: | ---: |
| Total cells | 8,061 | 8,480 |
| LUT1–LUT6 total | 5,155 | 5,367 |
| CARRY4 | 207 | 205 |
| Flip-flops | 2,316 | 2,316 |
| DSP48E1 | 12 | 12 |
| MUXF7 / MUXF8 | 214 / 48 | 353 / 117 |

The CSR combination increases mapped LUT/mux usage in this whole-CPU context.
Functional compatibility is established by these tests; an optimization benefit
for that combination is not established. Keep divider-only as the first parent
A/B candidate.

Final raw runs:

* Divider tests: build.rlR16S; combination CPU tests: build.qFckcv.
* Divider synthesis: synth.0vELzI/cpu.log and cpu.{coarse,xc7}.json.
* Combination synthesis: synth.KEGRoN/cpu.log and cpu.{coarse,xc7}.json.

An earlier synthesis attempt omitted the parent's allow-use-before-declare
option and failed elaboration; the script was corrected. An exploratory
post-XC7 ltp report in synth.9meGAe traversed library flip-flops and emitted
loop warnings, so its path/depth output is invalid and is not used as evidence.
The final runs omit that report and instead check SCCs before technology
mapping; both final runs report zero problems.
