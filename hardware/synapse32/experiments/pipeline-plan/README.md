# CPU pipeline next-stage plan

Decision: implement **look-ahead forwarding-control retiming at the existing
ID/EX boundary first**. Plain opcode predecode is less targeted: source-valid
bits and instruction IDs are already registered, and the measured path starts
at a registered source-valid bit. Splitting EX after the operand mux gives a
stronger structural cut, but requires new RAW interlocks, operand preservation,
trap ownership, and retirement gating. Keep that as the second candidate.

This directory owns only a plan, an isolated control prototype, and its evidence.
No shared RTL, sibling experiment, memory sequencer, fetch buffer, constraints,
clock, board build, or throughput measurement was changed. No synthesis, route,
bitstream, programming, or web research was run. The measurements below come
from existing local build artifacts, not a new physical experiment.

## Evidence and actual paths

The source list in `build-ddr-divider/synth.ys` selects the divider CPU,
execution unit, ALU and divider, with original sibling pipeline and CSR modules.
Use that combination, not the failed forwarding or CSR overlay, as baseline.
`evidence.json` captures hashes, the complete existing CPU path, and mapped
cell-to-RTL aliases. Paths below are relative to the repository unless marked
`Synapse32`, meaning the sibling `/Users/siriboi/github/synapse32` checkout.

| Existing evidence | Observation |
| --- | --- |
| `build-ddr-divider/route.log:1788–1848` | ID/EX rs1-valid Q to EX/MEM execution result bit 8 D: 23.9 ns, 3.1 ns logic + 20.8 ns routing; approximately 87% routing |
| Same log, final frequency lines 1946–1947 | CPU 41.81 MHz; system 61.02 MHz; both fail unchanged 100 MHz targets |
| `experiments/forwarding/BOARD_RESULTS.md` | Seed-4 forwarding rewrite: CPU 41.99 MHz, system 48.02 MHz; insufficient CPU gain with system regression |
| `experiments/divider/execution_unit.v:186–219` | MEM/WB/RF operand mux feeds full production ALU; same forwarded operands also feed address/branch/CSR logic and divider launch |
| `Synapse32/rtl/pipeline_stages/forwarding_unit.v:30–75` | Source-valid, rd equality/nonzero, producer-valid, late-result exclusion and MEM-over-WB priority are combinational in EX |

The mapped path is demonstrably forwarding, not just a guess from its name:
`parse_blif$198147` is a LUT5 taking `rs1_valid`, EX rs1 address bits 1/3 and
WB rd address bits 1/3. Its output goes through `198145` to `198226`, whose
inputs include RF, MEM and WB operand **bit 19**. The path then traverses several
LUT/MUXF7/MUXF8 networks and ends at EX/MEM result bit 8. Those later mapped
nodes are anonymous; this inspection does not identify every one as a specific
ALU operation, CSR term or shifter level. The route contains no CARRY4 or DSP
arc on this reported path. Do not call it the multiply or add critical path.

RTL fanout from the selected operand is concrete:

* `rs1_value/rs2_value -> alu -> exec_output -> EX_MEM.exec_output`.
* `rs1_value + imm -> effective_addr -> mem_addr`, plus alignment detection
  into exception/redirect/EX_MEM flush; AMO/LR/SC use rs1 directly as address.
* Branch compares use both operands; target is PC+imm. JALR uses
  `(rs1_value + imm) & ~1`; target alignment can trap.
* `rs1_value -> csr_exec` and CSR-file read data feed CSR result and write data.
  CSR writes serialize via PC+4 redirect. Privilege and pending IRQ are live EX
  inputs, not properties that can safely be decoded once from instruction bits.
* Both forwarded operands are captured by the divider on `div_start`.

Retiming removes comparison/priority work from before the operand mux; it does
not remove the mux, ALU, result selection, CSR loop or redirect/flush networks.
Even a successful CPU improvement leaves the separate system path. Neither
23.9/2 nor four extra flops predicts an attainable clock. 100 MHz is an unchanged
acceptance target, not an estimated or guaranteed result. Existing board reports
also retain DCI/tool signoff limitations.

## Candidate A: four new control registers, unchanged five-stage pipeline

Keep IF -> ID -> EX -> MEM -> WB and all existing architectural timing.
Add exactly `forward_a_q[1:0]` and `forward_b_q[1:0]`, clocked/reset with the
CPU at the ID/EX boundary. Codes remain RF=00, MEM=01, WB=10; never generate 11.
Feed these into the unchanged divider-baseline execution-unit muxes.
Do not combine this first candidate with masked mux rewriting or ALU predecode.

All existing ID/EX registers stay: rs1/rs2/rd addresses (5 each), rs1/rs2/rd
valids (1 each), immediate (32), opcode and instruction ID (7 each), PC (32),
RF operands (32 each), instruction-valid and instruction-page-fault (1 each).
EX/MEM and MEM/WB fields and their timing stay exactly as in the baseline.

The new flops capture the forwarding decision for **the state after the edge**,
using these projected tags from the pre-edge state:

| Projected state | Exact expression / source |
| --- | --- |
| Next consumer bubble | `pipeline_flush || (!pipeline_hold && hazard_stall)` |
| Next consumer rs1/rs2 tags | Existing ID/EX tags if hold, otherwise decoder tags; source valids forced zero for bubble |
| Next MEM rd / valid | Current ID/EX rd; valid = ID/EX rd-valid AND NOT existing EX/MEM flush expression |
| Next MEM instruction class | Current ID/EX instruction ID; irrelevant if next MEM invalid |
| Next WB rd / valid | Current EX/MEM rd; valid = EX/MEM rd-valid AND NOT `mem_stage_page_fault_taken` |
| Next WB write enable | Equals next WB rd-valid, as current `writeback.v` assigns `wr_en_out=rd_valid_in` |

For each next source: select next MEM if source-valid, matching nonzero rd,
producer-valid and not a late-result instruction. Otherwise select next WB if
source-valid and matching nonzero valid rd; otherwise RF. Preserve this exact
priority, including baseline fallback to WB when MEM is a load. The existing
hazard unit makes stale older-WB fallback unreachable for a real unresolved RAW;
the control replacement must nevertheless match the reference for arbitrary tags.

Late-result set is LB/LH/LW/LBU/LHU/LR.W and all nine AMO.W operations in the
existing forwarding unit. **SC.W is excluded from this set**: its MEM bypass
is `sc_result`, via `ex_mem_forward_result`; WB also gets the SC substitution.
Do not forward `module_read_data_in` or raw EX/MEM ALU data for loads/AMOs.

Use the CPU's existing EX/MEM flush exactly:
`div_wait || mem_stage_page_fault_taken || instr_stage_page_fault_taken ||
synchronous_exception_taken || interrupt_taken_qualified`.
A taken legal branch/JAL/JALR flushes younger work but must keep its own
EX/MEM entry (including a jump's link writeback). `pipeline_flush` is not an
interchangeable replacement for this expression.

Reset sets both selectors to 00. Recompute selectors on **every enabled edge**,
including ID/EX hold. On hold, use held consumer tags but advancing producer
tags; never hold these flops merely because the ID/EX instruction is held.
`forward_lookahead.sv` implements exactly this projection. Its `flush`, `hold`,
`stall`, `ex_mem_flush`, and `mem_page_fault` ports map respectively to
`pipeline_flush`, `pipeline_hold`, `hazard_stall`, the expression above, and
`mem_stage_page_fault_taken`. It is a helper, not a complete source-list overlay.

Implementation in an isolated complete overlay requires a CPU wiring edit and
this helper (or equivalent local registers inside the CPU). The helper takes
current ID/EX and EX/MEM tags and decoder tags; existing data mux sources remain
current EX/MEM result, current WB selected result, and ID/EX RF values. Never
register current forwarding outputs without projecting stage advance: that
would delay the decision by one instruction.

The new timing endpoints include decoder/tag compare -> selector D, hold mux ->
selector D, and exception/page-fault -> selector D. These can become critical.
The desired EX path becomes selector Q -> operand mux -> execution result D;
remaining fanout/routing and the ALU are still unmeasured. Local replication of
selector flops is a possible later measured experiment, not part of this plan's
four-flop candidate; synthesis may merge replicas unless explicitly constrained.

Pure predecode can be a later independent trial if new evidence points to
instruction-ID/result decode. Do not precompute CSR legality, interrupts,
forwarded data or fault decisions from ID. The source-valid bit is already a
predecoded register, so simply adding more opcode bits does not cut this path.

## Candidate B: operand boundary splitting EX, only if A is insufficient

Use IF -> ID -> X1 (forward operands) -> X2 (execute/resolve) -> MEM -> WB.
Retain ID/EX as ID/X1. Add the following **complete X1/X2 bundle**, clocked
on the existing enabled CPU edge; no new clock or memory handshake:

| New X1/X2 register | Width | Captured at X1 acceptance |
| --- | ---: | --- |
| `x2_valid_q`, `x2_instr_page_fault_q` | 1 each | Instruction token and fault metadata |
| `x2_pc_q`, `x2_imm_q` | 32 each | ID/X1 PC and immediate |
| `x2_opcode_q`, `x2_instr_id_q` | 7 each | Existing decode outputs |
| `x2_rs1_addr_q`, `x2_rs2_addr_q`, `x2_rd_addr_q` | 5 each | Existing register tags; rs1 needed for CSR immediate semantics |
| `x2_rs1_valid_q`, `x2_rs2_valid_q`, `x2_rd_valid_q` | 1 each | Existing source/destination valids |
| `x2_rs1_value_q`, `x2_rs2_value_q` | 32 each | Fully resolved X1 operands, including store/AMO data |

Total: **162 new state bits before synthesis**, plus any operand-hold repair
logic. No CSR read value, trap target, privilege, divider result, or interrupt
pending bit is latched in this bundle. X2 evaluates those live and owns execution.
Keep PC+imm and PC+4 arithmetic in X2 initially. Move the baseline execution unit
to X2 with forwarding inputs 00 and operand inputs from this bundle; relocate
forwarding muxes to X1. Keep original EX/MEM payload widths, now driven from X2.

Choose the conservative dependency policy: **no combinational X2-result to X1
bypass**. That bypass would send X2 ALU -> X1 operand register and can recreate
the long execute-plus-mux path this split was intended to remove.

For a valid X1 instruction and each used nonzero source:

1. Any matching valid writer in X2 blocks X1, even if an older MEM/WB matches.
2. Otherwise a matching MEM writer blocks if it is a load/LR/AMO. A ready MEM
   writer forwards its result, using SC result substitution.
3. Otherwise use matching WB selected data, then the saved RF operand.

On these RAW stalls, hold PC/IF_ID/ID_X1; allow X2 to complete once and insert a
bubble into X2 if no X1 acceptance. Independent issue may replace a completing
X2 on the same edge. Retain the original ID-vs-X1 load-use detector in the first
implementation for a conservative migration; X1 interlocks are still essential.
Its first load bubble overlaps the two-bubble load dependency schedule below.
An eventual removal requires its own cycle/ISA regression.

**Held operand repair is required:** while ID/X1 holds, update each saved RF
operand from a matching nonzero valid WB write on that edge. Keep instruction,
tags, PC and fault metadata stable. During acceptance use current MEM/WB mux
priority over the repaired fallback. This handles a different source whose
producer retires while X1 is blocked by X2 or DIV. Merely holding the baseline
ID_EX RF values is insufficient: registerfile write-through serves ID, not a
consumer already stuck in X1. X2's resolved operands hold unchanged during DIV.

Explicit transfer rules, in priority order:

* Reset clears valid/side effects in all stages and divider state.
* Selected redirect/trap kills IF/ID, ID/X1 and X1 acceptance. It clears X2
  after any permitted current-X2 completion; legal jump link data may still
  enter EX/MEM. Faulting/interrupted X2 must instead inject an EX/MEM bubble.
* Busy/incomplete X2 DIV holds X2 and ID/X1/front end; EX/MEM receives a bubble
  every progress edge, MEM/WB drains. Completion releases exactly one result.
* Otherwise X2 completes or is empty; accept ready X1, or clear X2 valid and
  insert a canonical bubble. Never duplicate an EX/MEM entry on an X1 stall.

Gate memory-class instruction IDs and rd-valid to canonical bubbles for invalid
X2. EX/MEM has no standalone valid bit; carrying garbage instruction IDs with
only rd-valid cleared can issue a store. Put all X2 side effects under a single
completion/selected-trap contract, rather than just adding a register to data.

## Flush, interrupt and side-effect obligations

For A, preserve all existing behavior and edge timing: PC redirect wins stall;
IF/ID flush wins hold; ID/EX reset > flush > hold > hazard bubble > advance.
Retain the baseline EX/MEM flush distinction above and fault suppression of
MEM/WB rd-valid/instruction ID. Older instructions drain during divide, each
memory request once. Branch, store and divider must use both selected operands;
CSR uses selected rs1 plus its unmodified register address.

For B, move EX-owned references in `riscv_cpu.v` as a group: divide classification,
start operands/mode, div wait/done ownership, exception PC, instruction-fault
PC/tval, fence-drain classification, execution inputs, EX/MEM inputs, WFI event,
return/CSR events and instret event all belong to X2. Leaving any on ID/X1 mixes
two instructions. Front-end hazard comparisons are the explicit exception.

Trap arbitration must produce mutually exclusive event strobes for the CSR file:
older MEM load/store page fault > X2 instruction page fault > qualified IRQ >
X2 normal execution decision (including its synchronous exception or redirect).
For simultaneous MEM load/store faults retain load-before-store cause priority.
The baseline execution unit checks IRQ before ordinary EX synchronous exceptions;
do not describe it as universally synchronous-exception-first. Live delegation,
privilege, mtvec/stvec and mstatus remain sampled at the resolution edge.

For B, mask MRET/SRET, WFI and normal CSR writes when an older fault or IRQ wins,
and mask younger EX exception strobes when the older MEM fault wins. The CSR file
currently prioritizes MRET/SRET ahead of its synchronous-exception arm: feeding
both an older page fault and a younger return can select the wrong action.
This is a baseline arbitration concern to test explicitly, not a bug claimed
fixed by the control prototype. A remains a strict behavior-preserving trial.

On IRQ in B, allow the older nonfaulting MEM entry to drain, cancel X2 (including
an in-flight divide), and squash X1/ID/IF. Resume PC is the oldest uncompleted
instruction: X2 PC if valid, else X1 PC, else IF/ID PC if valid, else fetch PC.
This avoids skipping an instruction when X2 is a dependency bubble. Baseline A
retains its existing EX-valid ? EX-PC : fetch-PC selection; the split cannot
blindly reuse that fallback. WFI's completed PC+4 redirect must establish the
resume address when the pipeline is empty. IRQ delivery must work with no valid
X2, and WFI wake through `mip & mie` remains distinct from globally enabled trap
delivery. Return retries canceled DIV from its own saved PC.

Divider reset/cancel wins launch/iteration/done. Suppress start on any selected
kill or non-divide stall; never start an instruction already canceled that edge.
Cancel collisions at launch, final iteration and consume must neither retire
nor write rd nor leak a younger store. An IRQ may cancel DIV while X2 is held;
do not gate trap handling solely with ordinary `x2_fire`.

Define normal `x2_fire` as valid and complete, with no blocking hold or winning
fault/IRQ. Retirement and CSR/WFI/return actions pulse once at their permitted
resolution edge. Legal taken branches and jumps still retire; trapping operations
do not. The baseline instret expression counts in EX, before a load can fault in
MEM, and does not explicitly gate instruction-page-fault outside the divide-wait
case. Do not call it a precise WB retirement interface. Preserve it for A;
for B test/document this inherited counter limitation separately from one-shot
X2 completion. Moving architectural retirement to MEM/WB is a separate design
change requiring carried completion metadata, not implicitly solved here.

Ordinary CSR reads/writes remain serialized as baseline; no speculative CSR
write in X1. AMO/LR/SC remain in MEM, with existing reservation/result behavior.
FENCE/FENCE.I/SFENCE.VMA and privilege/translation changes must squash younger
tokens as required by existing behavior; do not let a newly inserted X2 token
survive an instruction-stream serialization. Memory request handling and actual
translation remain out of scope, but use their existing fault inputs in tests.

## Latency and throughput budget

All figures are **enabled CPU edges**, not raw system cycles or DDR transactions.
They describe the specified conservative split with no X2->X1 result bypass.

| Case | Divider baseline / A | Candidate B |
| --- | --- | --- |
| Operand/execute stages before MEM | 1 | 2; +1 edge to MEM/WB and first result |
| Independent non-DIV instructions, ideal issue interval | 1 edge | 1 edge after fill |
| Adjacent ALU/MUL/link/CSR-result RAW | 0 data bubbles (serialization may add more) | 1 data bubble; dependent chain interval 2 |
| Adjacent load/LR/AMO RAW | 1 bubble | 2 bubbles; dependent chain interval 3 |
| Adjacent SC result RAW | 0 data bubbles | 1 bubble before MEM SC forwarding |
| Taken branch/JAL/JALR | Resolves EX; two younger front-end slots discarded | Resolves X2; three younger slots discarded, nominal +1 refill edge |
| Normal DIV/DIVU/REM/REMU | Launch + 32 iterations + consume; 33 extra stall edges | Same divider occupancy in X2; +1 operand stage, and dependent successor waits for result to reach MEM |
| Zero divisor / signed overflow | Launch + consume; 1 extra stall edge | Same X2 fast-path occupancy; +1 operand stage and RAW interlock if needed |
| WFI/return/CSR-write/FENCE.I redirect | Existing EX resolution | X2 resolution, nominal +1 front-end refill edge; exact costs depend on live events |

A adds four state bits and no designed instruction latency, bubbles, branch
penalty or divider iterations. B adds 162 bundle bits and more dependency stalls;
normal independent issue can still be one per enabled edge, not a promise of
one instruction per system cycle. A normal isolated DIV reaches MEM one edge
later with B; a dependent following instruction also incurs its X1 RAW wait.
Do not count DIV backpressure as 33 new added bubbles beyond the baseline.

For parent throughput work, compare useful completions/system cycles and enabled
edges/completion separately. A data-dependent workload needs a frequency gain
large enough to offset B's extra bubbles (2x for the ideal ALU RAW issue
interval changing from 1 to 2, and 1.5x for the load-to-dependent-consumer issue
interval changing from 2 to 3, before all other work/costs). These ratios refer
to the table's dependency intervals, not a whole
application prediction. Actual gated wall time includes every existing memory
sequencer phase, repeated held-PC fetches, and variable memory latency. Use the
parent's measurement results; this task did not add or modify that instrumentation.

## Bounded prototype results and implementation gates

Run from any directory:

```sh
bash /Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/pipeline-plan/verify.sh
python3 /Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/pipeline-plan/capture_evidence.py
```

Icarus Verilog 13.0 simulation passes **30,775** post-edge selector comparisons against the
actual sibling ID_EX, EX_MEM, MEM_WB and forwarding_unit modules. It includes
every 7-bit producer instruction ID, both source operands, simultaneous matching
MEM/WB producers, x0, reset, arbitrary flush/hold/stall/fault combinations, and
a held dependent DIV while older tags drain. Coverage reports 14 held-selector
changes, 158 MEM-hit edges and 21 WB-hit edges. WB wr-enable is tied to rd-valid
exactly as actual writeback RTL. The helper and testbench remain local.

This is a dynamic **control/tag** check, not exhaustive equivalence, CPU ISA
validation, data-value correctness, physical timing, or an integrated overlay.
The arbitrary-control portion deliberately includes unreachable pipeline states.
No full-CPU integration or optimization benefit is claimed.

Before promoting A:

1. Build a complete isolated divider overlay with CPU-only selector wiring.
   Prove the per-edge invariant `forward_{a,b}_q == baseline forwarding(projected
   ID_EX, EX_MEM, MEM_WB state)` inductively, including reset and all hold/flush
   priorities. Then prove full execution outputs equal under equal data/state;
   use production ALU, never the simplified `FORMAL` branch. Check all three
   multipliers are present and no combinational divider/modulo returns.
2. Run actual-CPU differential traces for RF writes, ordered memory requests,
   PC redirects, CSR writes, trap PC/cause/tval and counter events. A should be
   cycle-identical, including enabled-edge/system-cycle counts under matched
   external inputs. Compare both source operands and MEM-over-WB conflicts.
3. Reuse divider `cpu_tb.sv` and `cpu_collision_tb.sv` in continuous and unchanged
   gated-clock modes, with outputs/builds redirected under this experiment.
   Do not run sibling scripts that write to their owned directories. Baseline
   recorded broad counts are 1,067 completed divides, 1,355 stores and one read
   per mode; collision suite has 64 cases per mode. Run full upstream ISA tests
   as available, especially RV32M multiply/shift, RV32A, CSR/privilege and fences.
4. Add held-tag source combinations, back-to-back rd reuse, DIV with WB-to-ID
   write-through, pending IRQ with empty EX/WFI, and older load/store faults
   colliding with CSR/MRET/SRET. Preserve/triage pre-existing mismatches rather
   than silently widening a control-retiming patch.
5. Bounded synthesis only after functional checks: production Slang flags from
   `build-ddr-divider/synth.ys`, hierarchy/check, zero combinational SCCs, mapped
   flop count and path/fanout inspection. Confirm the old comparator is upstream
   of selector flops; compiler restructuring can erase the intended benefit.
   Parent may later authorize a same-seed physical A/B with unchanged XDC and
   all CPU/system clocks checked. No route is part of this bounded task.

Before attempting B, additionally require:

* Stage-aware scoreboard for all RAW distances 0–3, both operands, x0, same-rd
  multiple writers, load/LR/all AMOs/SC success+failure and dependent store,
  branch, JALR, CSR and divider. Hold X1 long enough for its other operand's WB
  producer to disappear; verify operand repair and no older-value fallback.
* Token accounting: no lost, duplicated or reordered completion; X1-stall
  bubbles never replay older stores/AMOs. Count accepted MMIO-like writes
  individually under gated memory backpressure, not just final RAM contents.
* Redirect/IRQ/fault matrix with X2 valid, empty, held, completing DIV, and X1
  blocked. Include simultaneous flush+hold, older MEM faults plus X2 return/CSR,
  younger fetch fault behind a taken branch, illegal/misaligned instruction,
  reset during DIV, WFI with pending globally masked/enabled interrupts, and
  MRET/SRET retry. Assert exact resume PC, one selected trap event, and no
  killed rd/CSR/memory effects. Inject only actual external fault/IRQ inputs.
* Move test observation points from baseline EX to X2. Use latency-tolerant
  architectural comparison; reschedule IRQs by observed instruction/phase,
  not old absolute cycle numbers. Counter-read values may differ legitimately
  with added edges; check defined deltas and inherited counter limitations.
* Confirm measured independent issue=1, adjacent ALU RAW=2, adjacent load RAW=3
  enabled-edge intervals, branch refill +1 and unchanged divider iteration
  count. Do not accept a clock gain that loses useful measured throughput.

Concrete next implementation is A's four-flop look-ahead helper integrated into
an isolated CPU overlay, with sequential invariant and actual-CPU differential
checks. B is a separately reviewable 162-bit operand-stage change with the
interlocks and trap contract above; it must not be smuggled into a mux rewrite.
