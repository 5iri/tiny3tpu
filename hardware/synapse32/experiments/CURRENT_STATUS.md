## Latest continuation: joint carry + read-valid OR

Lowest worst expanded interval is now **10.318 ns** (three probes:
10.252 / 10.252 / 10.318). Final integrity passes and all modeled CPU-related
domains are below 10 ns. DDR write-address detection remains limiting.
This candidate has 37 failing pairs versus OR-only’s 26; retain both.
See `build-grade2-joint-carry-read-or-partition-route/evaluation.md`.
No physical timing closure or fresh workload simulation is claimed.

## Latest continuation: read-valid OR partition

Best single-seed expanded result is now **10.324 / 10.324 / 10.337 ns**, with
26 failing endpoint/domain pairs versus 44 in timer-mid-zero-flag. Native
system/CPU is 97.49/100.53 MHz. Full integrity passes; no cells or execution
cycles added. See `build-grade2-read-or-arrival-partition-route/evaluation.md`.
100 MHz physical timing and hardware signoff remain unclosed. Earlier status
entries below are historical and do not supersede this result.

# Current timing and throughput status

## Full-SoC timing: NOT ACCEPTED

**Toolchain recovery verified:** rebuilt baseline objects and the KC705 chip
database match their historical hashes. Linked executables differ; an exact
saved-route replay reproduced complete routed JSON, timing graph and native
Fmax. Original manifests remain unchanged. New runs require the explicit
recovery control in `build-toolchain-recovery/transport-replay/manifest.json`.
Exact mixed-guidance and CPU-PREG replays also pass. All resumed critical-LUT,
capture-placement and DMA strobe routes now have completed expanded audits;
the recovered tools and database have persistent, hash-checked backups.

Latest retained stock-column diagnostic: **10.358 / 10.358 / 10.358 ns** from
`build-grade2-timer-mid-zero-flag-route`. Native partial reports are
**96.54 MHz system / 100.53 MHz CPU**. Final integrity passes with 94 planned
original-cell moves. **44 endpoint/domain pairs** still exceed 10 ns. This
candidate improves both the prior best period (10.391 ns, DMA-count flags)
and prior fewest failing pairs (52, CPU-reset/TPU-DSP-near). Those earlier
artifacts remain intact. No robust seed gain or physical acceptance is established.

The new candidate adds three redundant same-edge flags to the two inherited
DMA flags: one refresher predicate and two timer zero groups. Actual primitive
induction includes source initialization, synchronous reset/set and CE holds;
negative controls reject corruptions. No execution cycle is added. Parent
workload evidence is preserved compositionally; no fresh workload simulation
or whole-RTL synthesis is claimed.

The worst expanded path starts at DDR bank4 address FF77903 and reaches
read-valid9 at **10.358 ns**. CPU jump-address reaches **10.324 ns**, DDR
read-beat-offset **10.318 ns**, ready0 **10.297 ns**, and signed branch-less
**10.287 ns**. Timer placement cleanup and a two-macro capture rewrite
both pass integrity but regress global timing, so neither is selected.

Five further completed routes pass final integrity but do not replace that
baseline: shared capture predicate **10.938 ns**, all-capture early encoding
**10.382 ns** (51 failing pairs), whole capture-OR factorization **11.094 ns**,
OR/timer colocation **10.839 ns**, and CPU instruction-ID pair placement
**10.691 ns**. Each number is identical across the three expanded probes.
That earlier capture seed comparison was not run.

Six additional seed-5 routes now pass final integrity. Row-hit lookahead
reaches **10.980 ns**, two-level row equality **10.639/10.639/10.714 ns**, CPU
branch-decode placement **10.411 ns**, late-enable row-hit lookahead
**10.633 ns**, its 27-cell dead comparator cleanup **10.633 ns**, and the
branch carry-input inline candidate **10.358 ns** in all probes. The last
candidate ties the retained period but has 51 failing pairs; the placement-only
branch candidate has the new fewest, **43**, at 10.411 ns. The retained timer
candidate remains the period baseline with 44 pairs.

Local fixes are proved and routed: the branch-decode move closes the worst
jump-address input group to **9.104 ns**, and the carry-input inline candidate
closes the worst signed/unsigned branch-comparison input group to **9.247 ns**.
The revised row-hit flag input is **8.930 ns**, versus 10.980 ns before isolating
the late enable. No execution cycles or state-machine schedules change.
These local improvements do not establish full-SoC closure.

The paired [4,5,6] baseline/carry-input-inline comparison is complete and
passes integrity. Worst expanded intervals by seed are:

| Design | Seed 4 | Seed 5 | Seed 6 | Mean | Worst |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retained timer baseline | 10.614 | 10.358 | 10.686 | 10.5527 | 10.686 |
| Carry-input inline | 10.764 | 10.358 | 10.633 | 10.5850 | 10.764 |

All values are ns; neither closes timing, and the candidate regresses on both
mean and worst interval. `build-grade2-branch-paired-seed-summary-v2.json` binds
all six cases. A stale imported seed-label issue was caught and rejected;
removing only the two stale fields passed exact seed-5 routed JSON, timing graph
and native-clock replay before the paired runs restarted. Old records are intact.

The broader **394 carry-local LUT inlines** pass combined primitive SAT, full
routing and final integrity. This separate seed-5 candidate reaches
**10.358/10.358/10.502 ns**, with **46 failing endpoint/domain pairs**. Checked
CPU→CPU, CPU→system and system→CPU maxima are respectively **9.947, 9.584 and
8.591 ns**; no CPU-named state group remains above 10 ns. Remaining failures
are memory/DMA/accelerator paths. No execution cycles or state were added.
This is `build-grade2-joint-carry-buffer-inline-route`; it is not selected over
the retained global period baseline and has not had its own seed sweep.

A completed candidate moved the DDR write-address comparison before its
late low-adder carry. Actual constant provenance and primitive SAT reduce the
early cofactors to 49 LUTs plus one final carry-select LUT; two unused original
macro children are removed with observer/state/constant negative controls.
`build-grade2-write-address-carry-choice-route` passes routing and integrity,
but regresses to **11.120/11.120/11.320 ns** and is rejected. A placement-only
move of thirteen unchanged low write-address registers fails the first
placement legality check; corrected v2 excludes slice X-input conflicts and
passes full routing and integrity at **10.633 ns** in all probes. It reduces
failing endpoint/domain pairs from 46 to **31**, the new fewest, and lowers
the read-beat-offset maximum from 10.502 to **10.068 ns**. Its moved-register
input maxima are D **1.569**, CE **9.492**, SR **4.154 ns**. No logic or
cycle count changes. This is `build-grade2-write-low-address-move-v2-route`.
The retained best global period remains 10.358 ns. See
[the current DDR iteration](carry-guidance/NEXT_WRITE_ADDRESS_CARRY_CHOICE.md).
Stage 20 revalidation passes **53 seed-5 candidates / 3,094 hashes**, including
the completed seed comparison as a separate control.
Physical coverage remains incomplete: generic/carry timing, skew/hold, reset
and DDR IO/calibration remain separate open requirements.

The following paragraphs retain earlier experiment history; current status
is the retained result above and the latest entries at the end of this file.

The CPU branch-control collapse and its following 13 critical-LUT collapses
both finish at **10.620 / 10.620 / 10.697 ns**, with native **93.48 MHz system /
101.25 MHz CPU**. Moving DDR write-data capture closes that local D path to
**8.287 ns**, but its global worst becomes **10.720 ns**. All integrity audits
pass; none replaces the retained result.

DMA write-strobe late cofactoring then reaches **10.557 ns in all three probes**
(native **94.72 MHz system / 100.53 MHz CPU**). Its capture-placement combination
regresses to **10.813 ns in all three probes**. Both final audits pass, and both
full timing gates reject. The strobe-only route now has a DDR read-response
critical path. Cofactoring its 55-input selection cone passes exact BDD and
primitive SAT, but its 56 extra LUTs worsen routing to **14.334 ns** in all
probes; it is rejected. A direct capture-placement experiment on the retained
transport design reaches **10.526 ns** in all probes, also not selected. Both
final integrity audits pass. These are same-clock/firmware fixed-layout route
experiments. Minimizing the large cofactor from 56 to 36 added LUTs still
reaches **12.960 ns** in all probes. The four-LUT read-address CE cofactor
reaches **10.620 / 10.620 / 10.740 ns**. Both final integrity audits pass and
both are rejected. The UART write-enable cofactor reaches **10.557 ns** in
all probes; its one-early-LUT minimized variant reaches **10.651 / 10.651 /
10.751 ns**. Moving the DDR data-source LUT/FF macro reaches **10.620 /
10.620 / 10.720 ns**. All three final audits pass and none is selected.
Shared UART decode collapses reach **10.475 / 10.475 / 10.605 ns**; the
two-bit AR encoding reaches **10.620 ns** in all probes. Their targeted local
fixes include UART LCR CE at **7.844 ns** in the minimized-LCR route and
read-address CE at **9.577 ns** in the AR-encoded route. Returning final LUTs
to their original BELs does not improve the global result. Combining shared
UART collapses and AR encoding finishes at **10.597 / 10.597 / 10.697 ns**;
all these final integrity audits pass and their timing gates reject. The next
bankmachine-valid collapse is routing, followed by a joint four-strobe rewrite
under proof. No 100 MHz closure is claimed.

The changes compose with unchanged parent firmware/workload proofs. No added
CPU cycle, instruction, fresh workload simulation or whole-RTL synthesis is
claimed. Generic/carry delays, clock skew/hold, reset recovery/removal and DDR IO
remain unvalidated. No physical timing acceptance or promotion has occurred.
See [the enable, reset and CPU control record](carry-guidance/MAIN_CE.md).

The separate all-column stress category below remains unchanged.

The best **all-column stress** expanded diagnostic is the proved four-DSP output-register mapping
plus the collapsed Wishbone command-enable LUT:
`build-ddr-cpu-preg-wb-lut-weight40-route/seed-4`, with **11.746 ns in all three
probes** (previous: 11.776 ns). Native reports are **85.51 MHz system /
106.13 MHz CPU**. CPU-to-system DSP input timing remains the longest expanded
path. Integrity passes and the complete timing gate still rejects 100 MHz.
Firmware and workload counters are preserved through actual parent workload
checks plus DSP induction and exhaustive LUT equivalence. This derived mapping
is not a fresh RTL synthesis or mapped-netlist workload simulation. Seed 8 is
12.078/12.078/12.278 ns and is not selected.

The one-predicate Wishbone capture passed primitive temporal induction but
regressed expanded timing: seed 4 is 12.113 ns; seed 8 reaches 12.459 ns.
Both integrity audits pass and both timing gates reject. It is not selected.

The multiplier signedness experiment passed exhaustive cone checks and primitive
induction, with no new execution cycle. Fresh seed 4 is 11.375/11.375/11.910 ns;
seed 8 is 12.707/12.707/12.807 ns. Both integrity audits pass. The carry-cost
probe prevents promotion despite the improved zero-cost probe.

Unused DSP A[29:25] tie-offs also pass actual DSP-model induction for all four
profiles with only P observable. Expanded seed 4/8 results are 12.236/12.224 ns,
so they are not selected. CPU-only native 104.44 MHz in seed 4 does not establish
SoC closure: the CPU-to-system DSP input still exceeds 10 ns.

The converter state group improved from 11.776 to 11.192 ns with the LUT
collapse; its new worst trace is a different state-feedback path. Combining
captured multiply modes with it regressed to 12.377/12.377/13.132 ns. The fresh
RTL descriptor-range experiment preserved every workload field but routes worse:
13.422/13.422/13.622 ns with MREG, 12.435/12.435/12.635 ns with PREG. None is
selected.

The second, exit-code LUT collapse routes at 12.078 ns. Twelve simultaneous
proved LUT collapses route at 12.138 ns. Extra seed 2 reaches 12.419 ns; seed 5
has a CPU-to-system DSP path at 12.237 ns despite native system 89.84 MHz. None
replaces the retained result.

The isolated [clock-domain criticality aggregation fix](carry-guidance/DOMAIN_CRITICALITY.md)
passes regression tests and exact disabled replay. Enabled seed 5 improves its
own previous result from 12.237 to 11.858 ns, but neither enabled seed replaces
the retained 11.746 ns result. All-column aggregate stage 15 verifies 45 routes
and 3,199 hashes, with no physical timing acceptance.

A separate [stock KC705 timing-column comparison](carry-guidance/KC705_GRADE.md)
is now verified. UG810 and the repository specify -2 at nominal 1.0 V; prior
registered-DSP/RAM/LUTRAM limits took maxima over all six speed/voltage columns.
Re-evaluating the identical seed-5 route with the stock column gives
11.448/11.448/11.572 ns. This is a model refinement, not a hardware speedup;
its gate still rejects. The all-column results remain separate and unchanged.
The new grade-column backend passes exact disabled replay. Fresh seed-5 routing
with those costs reaches 12.557 ns in the worst probe, so it is not selected.

A second route compares a proved pure-combinational multiply-sign factoring:
one shared instruction-prefix LUT5 and two LUT4s replace the deeper sign cones,
with exhaustive checks of all 512 original instruction/sign cases. It introduces
no register, cycle or firmware change. Its fresh route reaches 13.743 ns in the
worst probe and is not selected. Denser beta=0.6 placements also regress to
16.535 ns (weight 40) and 15.465 ns (weight 100). All four integrity audits pass;
all timing gates reject. Stock-column aggregate stage 1 records these separately.

The direct branch predicate passes all 1024 instruction/condition cases and
independent primitive-model SAT, without adding state or an execution cycle.
Its stock-column worst probes are 12.163 ns (seed 4) and 11.810 ns (seed 5).
Folding the following opcode guard into its final LUT passes all 4096 cases
and primitive SAT; it reaches 12.599 ns (seed 4) and **11.169 ns in all probes
(seed 5)**. The latter is the new best stock-column diagnostic, native
**89.53 MHz system / 96.60 MHz CPU**. It still fails timing. The matching
retained-netlist seed-4/5 results are 12.117/12.557 ns, so the gain is not uniform
across placement seeds. No default is promoted. Stock-column aggregate stage 2
verifies ten fresh routes and the two earlier reanalyses.

The new worst seed-5 trace is DDR command-ready control. The proved two-LUT to
one-LUT replacement regresses to 14.042 ns. Collapsing two remaining branch
carry/decode cuts into exact LUT6s reaches 11.115/11.115/11.196 ns, native
89.32 MHz system / 100.30 MHz CPU, and does not replace the best diagnostic.
All 2048 cases and two independent primitive SAT proofs pass. Its first proof
harness omitted an input driver on an unobserved upper carry output; corrected
v2 includes every primitive input and passed `check -assert`. The failed harness
is retained.

Seven same-edge local instruction-register copies pass actual FDCE/FDPE reset
sequence and induction proofs. Their route improves CPU-to-system diagnostic
timing below 10 ns but regresses globally to 12.019/12.019/12.119 ns. All three
follow-up integrity audits pass and all timing gates reject. Stock-column
aggregate stage 3 covers 13 fresh routes plus two reanalyses. The best remains
11.169 ns, with no default promotion or physical timing acceptance.

The current guarded-branch DSP upper-input tie-off passes all four actual DSP
profile induction proofs and improves the best stock-column result to
**11.093 ns in all three probes**, native **90.15 MHz system / 102.74 MHz CPU**.
Its integrity audit passes; timing still fails. The new worst path runs from
the DDR ZQCS timer through maintenance-control logic. Stock-column aggregate
stage 5 covers 15 fresh routes, two reanalyses and three control records.

The isolated optional checkpoint exporter passed exact routed JSON, native
guidance-graph and Fmax replay. A separate [standalone DSP slot option](carry-guidance/FREE_DSP_SLOTS.md)
passes actual packer/cascade tests and exact disabled replay. Its enabled route
legally uses 19 upper slots but regresses to 11.740 ns; it is not selected.

The next candidate captures the ZQCS zero predicate on the existing counter
edge. Full control-cone SAT and actual mapped counter/FDRE/FDSE induction prove
the flag equals `count == 0`, including arbitrary synchronous reload and the
specified initial count of 99,999,999. Maintenance event timing is unchanged.
Its seed-5 route reaches 11.358/11.358/11.603 ns, with a passing integrity audit
and rejecting timing gate. The targeted maintenance endpoint improves from
11.093 to 8.798 ns; CPU read-data arithmetic through memory-sequencer control
becomes the longest path. The matching parent seed-4 route reaches
12.327/12.327/12.427 ns. Stock-column aggregate stage 6 verifies 17 fresh routes,
two reanalyses and three controls. No physical closure or default promotion is
claimed.

The latest stock-column minimum worst probe is **11.038 ns**, from a
[same-cycle sequencer choice rewrite](carry-guidance/SEQUENCER_CHOICES.md).
Its seed-5 probes are 10.936/10.936/11.038 ns; native reports are 90.60 MHz
system / 97.99 MHz CPU. Matching seed 4 reaches 11.774 ns. Both integrity audits
pass, both timing gates reject. The targeted sequencer endpoint improves from
11.603 to 9.317 ns. The next worst path is DDR write-address change detection
into a native-port converter selector. The failing endpoint/domain-pair count
increases to 319, so this is not a uniform endpoint improvement or a promotion.

Sign factoring on the retained parent reaches 11.752 ns; combined with the
timer flag it reaches 12.312 ns. A smaller sequencer mux collapse reaches
12.601 ns; captured multiply signedness reaches 11.825 ns. All are rejected.
These are isolated mapped-netlist experiments composed with parent workloads
and equivalence proofs, not new full-workload simulations. Stock-column stage 8
verifies 24 fresh routes, two reanalyses and four controls.

The current parent checkpoint replay is exact. Fixed-layout reimport exposed
post-route loss of 13 logical labels on constant-ground inputs; no dynamic
logical input loss was found in that control. An isolated optional backend fix
preserves labels on pins untouched by a routing permutation. Disabled replay
is exact; enabled replay changes only those labels, with identical routing,
placement and native Fmax. The logical-port audit expands shared-pin labels,
requires every LUT input and RAM address/control input, and verifies every
cell/parameter/logical connection against the pre-fixup checkpoint. It passes.
The initial strict comparison failures are retained, and no fixed-layout timing
result is promoted. See [pin-label control evidence](carry-guidance/PIN_MAPS.md).

The next DDR comparison factorization passes a 50-input primitive SAT proof
and improves its measured selector endpoint from 11.038 to 9.669 ns, but its
global probe is 11.853 ns. Placement weights 10 and 20 also regress to 11.641
and 12.338 ns. The best stock-column result remains **11.038 ns**.

The fixed-layout flow now supports verified bounded moves. Moving one complete
three-cell timer-control macro improves the fixed-layout control from 11.351 to
11.141 ns; two valid destinations give that same worst probe. Every other cell
location and every logical connection is preserved. A third destination fails
original placement validity and is retained as a failed experiment. All valid
route integrity audits pass and every timing gate rejects.

The new fixed-layout bottleneck is DMA descriptor validation into
`write_pending`. `build-dma-descriptor-abstraction/results.json` proves that its
207-cell mapped D cone depends on the 96 address/length bits only through
descriptor validity, for all 182 independent cut inputs. The separately mapped
narrow predicate/control candidate now passes actual-primitive SAT and its
route integrity audit. Its write-pending D endpoint measures **9.219 ns**, but
CPU jump-address decode becomes the worst path at **11.591 ns in all probes**.
It is not selected. No registers, execution cycles or firmware bytes change;
workload preservation is compositional proof over the measured parent, not a
fresh mapped-netlist workload run.

A three-LUT jump-address decode cone has also been reduced to one LUT5, with
all 32 independent input combinations verified. On the DMA candidate, the
jump-address endpoint improves from 11.591 to **8.430 ns**, but reset/control
into DMA output-FIFO write enable becomes the worst path at **12.312 ns**.
On the retained best parent, jump-address measures 9.681 ns and the global
probes are 11.491/11.491/12.191 ns. Both integrity audits pass; neither route
is selected and both timing gates reject. A reset-control cofactor rewrite
passes actual-primitive SAT over 13 independent inputs, adding three LUTs and
no registers/cycles; its seed-5 route reaches 13.023/13.023/13.978 ns.
Integrity passes, but it is not selected. Its FIFO cell maximum input is
8.955 ns (DI1, bounding WE); a DMA byte-count-to-framing path becomes critical.
The initial helper-only
synthesis attempt rejected connection-free Yosys scope metadata; the corrected
v2 explicitly checks and ignores that metadata, with the failed attempt retained.
Stock-column aggregate `build-kc705-grade2-limits/iterations-summary-stage13.json`
passes: 31 full-placement routes, three fixed-layout routes, two same-route
reanalyses, eight controls and 1,448 verified hashes. All-column stress scores
remain separate. No full-SoC timing acceptance or default promotion is claimed.

The [packed logic edit flow](carry-guidance/PACKED_LOGIC_EDITS.md) now changes
one proved LUT while preserving every physical cell location. The unchanged
control reaches 11.533 ns; the jump-decode edit reaches 11.728 ns, so neither
replaces the best 11.038 ns result. Both integrity audits pass and both timing
gates reject. A first wire-reuse control established that the old placement
checkpoint contains no physical routes; it exactly reproduces the unchanged
control. A separate post-route checkpoint and lossless pip-ID exporter now pass exact
replay checks (only saved pip-ID encoding differs in the lossless version).
The first actual imports fail placement, constant routing or logical equality;
these are rejected. A control filtering for exact physical-pin compatibility
passes logical integrity but regresses to 14.140 ns. Locking all 20,278
compatible data routes preserves every one of their wire/pip resource sets
and reaches **10.781/10.781/11.038 ns**, native **90.60 MHz system / 100.53 MHz
CPU**. All logic and cell locations match; 311 endpoint/domain pairs still
fail versus 319 in the retained full-placement result. Its timing gate rejects.
The whole-SoC worst interval remains 11.038 ns; no promotion is made.
Stock-column stage 16 verifies 31 full-placement routes, seven fixed-layout
results (including one logic edit), two reanalyses, fifteen controls and 1,584 hashes.

The authoritative current check is
`python3 tools/synapse32_check_soc_timing.py --route ... --sensitivity ... --out ...`.
The two historical candidates discussed next return **exit status 2**. Missing coverage or unvalidated
delays cannot be treated as a pass. See [the concrete missed paths and commands](timing-check/README.md).

The partial-100.29 MHz candidate has a traced **DMA write address → last-cycle
flag** path with eight missing native carry connections and a **17.773 ns**
expanded interval even with carry/PCOUT substitutions at zero. The better
expanded candidate has a **reset → boot-RAM write-enable** path at **11.936 ns**;
the native backend ignores its RAM capture endpoint. A DDR write-count path
is **12.105 ns** with symbolic carry cost. These diagnostics do not prove
physical delays, but they prevent 100 MHz acceptance.

The original backend omits carry connections. The carry-guided backend includes
them with assumed costs; its actual native graph is separately checked from
its normalized comparison graph. Both still lack complete validated timing.
The gate and existing graph/primitive tests pass (23 tests in the earlier
coverage audit; the 10 checker tests were rerun during the RTL work below).
That earlier audit changed no RTL, firmware, constraints or workload cycles.

## Expanded native coverage and further RTL work

The [CSR, DMA and mixed-timing experiments](boot-ddr-first/CSR_TIMING.md) add
proved read-DMA address updates, direct burst counts, 70-address CSR readback,
and same-edge CPU arithmetic rewrites. All completed workload comparisons
retain identical IPC and system cycles. The dual-DMA primitive-guided route
has probes **12.072/12.072/12.155 ns**, close to but still worse than the
retained baseline. Later combinations include regressions and remain isolated.

The optional native backend now includes current-profile boot RAM, registered
multiply DSP and **mixed LUTRAM write-clock/read-address** timing. Disabled
replay is byte exact. Enabled graphs reproduce the independent primitive
models, including **20,824 LUTRAM clock-check rows**. Routed microtests verify
that neither LUTRAM origin can disappear from the native timing walk.
These are coverage improvements, not physical signoff. A timing-weight-40
route gives **12.118/12.118/12.312 ns**; 100 MHz remains unclosed.

The latest DDR prefix experiment removes ten dependent upper-address carry
cells in total without changing register counts, firmware bytes, IPC or workload
cycles. Its arithmetic and live-net structure checks pass. Two fresh routes completed at **12.894 ns** and **12.500 ns** in all three
expanded probes; neither is a routed timing improvement over the retained baseline. The keep-only version
completed at **12.281/12.281/12.581 ns** and remains rejected. See the detailed
[iteration record](boot-ddr-first/CSR_TIMING.md), including a corrected structural
check that rejects disconnected debug aliases as timing endpoints.

The UART occupancy rewrite completes at **12.268/12.268/12.368 ns**, preserving
all workload counters. A multiplier register-boundary candidate passes proofs
and workloads but infers unsupported DSP timing profiles and remains unranked.
A separate four-DSP MREG-to-PREG mapping preserves every other synthesized cell
and passes actual primitive-model induction. Its timing extension passes disabled
byte-exact replay; two corrected candidate routes are in progress. The initial
mapping attempts failed import on missing new-pin direction metadata and produced
no timing result. Details and all retained failures are in the iteration record.

## Critical-path RTL fixes and placement consistency

The [boot/DDR/DMA experiments](boot-ddr-first/README.md) now implement and prove
local boot acceptance, DDR first-beat state, parallel queue counters, direct
availability comparison, DMA terminal detection and carry-select DMA address
updates. Fresh smoke and 45-shape CPU/DMA/TPU runs exactly preserve **all**
PROFILE, METRICS and DMA fields, including **0.796208 full-diagnostic IPC**
and **11,544,608 system cycles**. Board-controller changes are separately
proved; those workloads still use variable-latency memory rather than a DDR3
PHY simulation. Firmware and original XDC bytes remain identical.

For the combined address-advance candidate, matched expanded path groups
improve from **11.345 to 7.233 ns** (DMA last-cycle flag), **11.030 to 8.977 ns**
(DMA address), and **11.936 to 10.201 ns** (boot RAM). Its whole-design probes
are **12.326/12.326/12.526 ns**, with a CPU branch path now longest; this still
loses to the selected baseline's worst probe of **12.105 ns**. The complete
route table includes regressions and a DMA-only ablation. Evidence includes
`build-ddr-boot-first-advance/iteration-integrity.json` and
`build-ddr-boot-first-advance-coverage/report.json`; integrity passes while
timing remains explicitly rejected.

Branch predicates are now proved in the existing operand-capture stage, with
no extra stage, instruction or predictor. Fresh workload counters are again
exact. Two legal branch routes give **12.376/12.376/12.376 ns** (seed 4) and
**12.720/12.720/12.920 ns** (seed 6). Seed 4's boot-RAM group is **8.990 ns**;
its longest path is instead CSR address decode into a DDR PHY bitslip-counter
enable. Seed 6 reports native CPU **108.83 MHz** but system **77.40 MHz**;
it is not an overall improvement. Seed 8 fails placement legality and has no
accepted timing result. `build-ddr-boot-first/iteration-summary.json` checks
12 completed route/model pairs and retains the **12.105 ns baseline** as the
best expanded diagnostic. None of these intervals validates physical Fmax.

The [carry-guidance backend](carry-guidance/README.md) also makes timing-port
classification and carry dependencies consistent before placement. Disabled
replay is bit exact. Enabled baseline and address-advance routes are byte
identical to their placed-only counterparts, so this backend correction
provides no timing gain in those comparisons. Symbolic carry costs remain
unvalidated. No physical timing claim or hardware default is promoted.

## Earlier partial native-report milestone — not SoC timing closure

**Actual routed native report: 100.29 MHz system / 106.38 MHz CPU**, seed 4.
The related system/CPU paths report **9.16/9.61 ns** against unchanged 10 ns
budgets. This reaches the requested **native nextpnr diagnostic** target.
It does **not** establish physical KC705 timing closure: the native model's
missing arcs and unvalidated delays still apply. System margin in the native
model is only about **29 ps**.

The [DDR/local-placement candidate](ddr-local-decode/README.md) combines four
parallel reset copies, one exhaustively proved five-input DDR decode,
two DDR timer-control LUT moves, and relocation of two TPU operand LUT/FF
pairs. No pipeline stages or instructions are added. The source configuration
was freshly checked against the current smoke/45-shape workload; all PROFILE,
METRICS and DMA fields match exactly. The final post-mapping changes are
functionally proved; these workload tests are not gate-level DDR3 simulation.

Evidence: `build-ddr-route-reset-decode5-pe-seed4/route.log`,
`incremental-decode-integrity-v4.json` and `native-goal-verification.json` in
that directory. The route preserves **20,074** verified nets. The audit
requires exact retained physical resources and delays, all variable-input
logical cell arcs, clock/output classifications, and all five arcs of the
changed decode. Native timing equations and routing legality are unchanged.
A lossless routing serializer passes an exact ordinary-route/timing-graph
control replay. Firmware and original XDC bytes remain identical.

The native winner gives **17.773/17.773/18.663 ns** in the expanded symbolic
probes, versus **11.936/11.936/12.105 ns** for the best UART candidate below.
These are separate rankings; the native winner is worse under expanded coverage.
`python3 tools/synapse32_native_iteration_summary.py` binds 17 completed route
records to `iteration-summary.json` in the selected native route directory. No board frequency/default is promoted and no board is programmed.

## Physical 100 MHz goal remains open — latest RTL diagnostic

**Open-source-only workflow. Physical 100 MHz timing is not yet closed.**
Actual Yosys synthesis and nextpnr placement/routing target KC705
`xc7k325t-ffg900-2`, with the original XDC and `--freq 100`.

The selected expanded diagnostic now includes [UART reset control](uart-reset-control/README.md),
with the previous UART local acceptance, atomic-word, address decode and DMA
capacity changes. Carry-guided seed 8 gives **11.936/11.936/12.105 ns** under
symbolic PCOUT/carry probes 0/0, 1/0 and 0/0.1 ns. The preceding selected
UART-local seed 4 gave 12.398/12.398/12.552 ns. This selection minimizes the
worst of the three probes; it is not validated device timing.

That route's incomplete native report is **82.61 MHz system / 90.32 MHz CPU**,
including symbolic carry costs. With the original backend, the UART parallel
readback plus divider-sign candidate reaches **93.70/108.93 MHz**, but its
expanded probes are worse: 13.577/13.577/13.977 ns. Original and carry-guided
native reports have different arc coverage and must not be directly ranked.
The older local DDR placement reports 97.53/101.68 MHz. The incremental
routing candidate above reaches the requested native >100 MHz report.

All four RTL experiments pass formal checks and exactly preserve every
PROFILE, METRICS and DMA field in fresh smoke and 45-shape runs. The older
parallel-chooser configuration was also freshly revalidated against these
same workloads and firmware. Full diagnostic: **11,544,608 system cycles**,
**1,659,843 instructions / 2,084,686 enabled CPU edges = 0.796208 IPC**.
GEMM windows remain **5,479,755 system cycles and 0.801148 pooled IPC**.
Tests include CPU, DMA and TPU with variable-latency memory, **not LiteDRAM/PHY
simulation or on-board DDR3**. Firmware and XDC remain byte identical.

The UART reset change removes a redundant combinational enable mask while
preserving reset-prioritized state and FIFO payload writes. Whole-UART proof
covers 483 comparison points. Synthesis uses 627 CARRY4, 6,413 LUT6, 7,411 FDRE,
6,366 FDCE, 36 DSP48E1 and 16 RAMB36E1: 26 fewer LUT6 than UART local alone.
[Multiply carry-save](mul-carry-save/README.md),
[divider sign selection](divider-sign-select/README.md) and
[parallel UART readback](uart-read-parallel/README.md) are separately proved
and measured; none replaces the selected expanded diagnostic.

`python3 tools/synapse32_reset_iteration_audit.py` verifies **44 manifests,
12 routes**, all recorded artifact hashes, and exact smoke/45-shape results.
Evidence: `build-uart-reset-control-proved/iteration-integrity.json`.
Earlier evidence remains in `build-uart-local-burst-proof/iteration-integrity.json`.
No hardware defaults, firmware behavior or sibling CPU repository changes
are promoted. No board is programmed.

Native timing omits registered DSP/BRAM/LUTRAM timing; the original backend
also omits carry arcs. The expanded model covers those primitive profiles but
uses symbolic carry/cascade delays. Generic FF, clocks, hold, reset recovery
and I/O still lack validated signoff. All full-SoC timing acceptance flags
remain false.

**Latest correction: the baseline backend also omits every carry-cell arc.**
All 662 used CARRY4s have zero internal delay arcs, cutting arithmetic paths.
No verified whole-SoC Fmax is established; the old 97.53 MHz is an incomplete
report, not evidence that only 0.253 ns remains. New offline models cover the
four registered CPU DSP profiles, sixteen boot RAMs and 2,603 observable
RAMD32 cells. Carry delays and one DSP cascade clock delay remain symbolic,
and generic FF/clock/IO timing still needs validation. See
[core timing findings and evidence](core-timing/README.md).

**Previous selected expanded diagnostic candidate: 13.961 ns, seed 4.** The
[atomic-word input bypass](atomic-word/README.md), UART decode and
[boot prefix decode](boot-address-decode/README.md), together with DMA read
comparison, reduce the previous best 15.520 ns interval to 13.961 ns with
zero substituted unknown delays. With 0.1 ns per missing carry arc, the best
comparison is 15.720→14.661 ns. This is not a physical Fmax claim or 100 MHz
closure. The longest endpoint is now DMA write `output_last_cycle_reg`.

All three new combinations preserve complete smoke/45-shape PROFILE, METRICS
and DMA records exactly. The atomic change has an inductive output/state
proof including arbitrary forwarding; boot and UART decodes have exhaustive
symbolic address proofs. The full combination removes eight CARRY4s and 44
LUT6s relative to DMA read comparison alone, with no register, DSP, BRAM,
firmware or constraint changes. It remains opt-in; board defaults are unchanged.

The latest [DMA write last-cycle](dma-write-last/README.md) and
[direct length/page predicate](dma-write-short/README.md) experiments pass
formal proofs, the 27-case DMA/TPU unit suite and exact smoke/45-shape profiles.
Six routes were evaluated. The smallest zero-substitution value is 13.835 ns,
but its 0.1 ns carry probe is 14.695 ns versus the selected candidate's
14.661 ns. The direct-predicate version and its extra seeds likewise fail to
improve across the probes. Neither is selected as a replacement; 100 MHz
remains unclosed and no physical Fmax is established. Their remaining long
paths include write address/count updates and pending control. A separate
range proof established the 0..64-byte burst-size bound used by the newer
capacity experiments above; wrapping beat counters retain their widths.

The new [DMA read-comparison experiment](dma-read-compare/README.md) has formal
proof, 27 passing DMA unit cases, exactly unchanged smoke/45-shape performance,
and passing synthesis. In the expanded seed-8 graph, worst interval improves
17.320→15.520 ns with zero unknown-delay substitutions and 17.910→15.720 ns
with 0.1 ns per missing carry arc. These are sensitivity comparisons, not
physical Fmax claims. Candidate seed 4 is worse. No board default is promoted;
validated Kintex timing coverage is still needed to verify physical 100 MHz.

The subsequent [UART address decode](uart-address-decode/README.md) preserves
the exact inclusive range while replacing the wide comparison with bit checks.
Proof covers all addresses and base values, including unaligned accesses.
Smoke/45-shape profiles, firmware bytes and constraint bytes remain exact;
synthesis removes four more CARRY4s and 25 LUT6s without changing register,
DSP or BRAM counts. Expanded route comparison is recorded with that experiment.
Its best tested interval is 16.875 ns versus the DMA-only candidate's 15.520 ns
at zero symbolic substitutions. It remains optional, not a new timing winner.

## Earlier results with incomplete timing coverage

The MHz values and candidate rankings in this historical section were based
on the incomplete backend. They do not establish whole-SoC Fmax or the size
of the remaining 100 MHz timing gap; use the corrected coverage discussion above.

The [boot-RAM timing model](bram-timing/README.md) now covers all sixteen current
RAMB36E1 profiles. It leaves the covered global maximum at 10.253 ns and exposes
an additional 10.173 ns RAM-enable violation; RAM read-origin paths reach
8.025 ns. A [local boot-enable candidate](boot-local-enable/README.md) removes
irrelevant external-ready decoding without adding a cycle. Formal equivalence,
exact smoke/45-shape profiles and synthesis pass. Seed 8 improves RAM input
maximum from 10.116 to 9.902 ns, but regresses overall system Fmax from 95.39 to
88.65 MHz (CPU 100.52 to 102.48 MHz). Seed 4 is worse. This candidate is rejected
as a replacement for the retained design. Other timing-model gaps below remain
unresolved.

**Timing coverage correction (2026-09-11): no full-SoC Fmax is established.**
All routed MHz figures below are partial diagnostics. Inspection of the exact
baseline nextpnr source found that registered DSP48E1 profiles (including four
existing CPU multiplier DSPs), all sixteen RAMB36E1 boot-memory blocks, and
LUTRAM write ports are omitted from timing classification. The PE accumulator
candidate also uses registered DSP outputs and cannot be assessed with that
model. The 97.53 MHz result is reproducible for covered paths, but the stated
0.253 ns shortfall is only for those paths. Closing it alone would not prove
100 MHz. Coverage and delay-model validation must precede acceptance; DDR PHY
I/O and physical clock/reset signoff remain additional limitations.

The live routed-graph audit now reproduces all 998 covered endpoints exactly
and verifies all 251,922 connected ports. See
[timing coverage evidence and remaining model work](timing-coverage/README.md).
Flip-flop timing also uses generic 0.1 ns values requiring validation; port
coverage alone cannot establish accurate delay bounds.

Functional and throughput measurements are unaffected: the PE candidate passes
cycle equivalence, mapped primitive simulation, and exact smoke/45-shape profile
comparisons. Firmware and board defaults remain unchanged.

The latest **legality-checked local placement** reaches **97.53 MHz system /
101.68 MHz CPU**, with crossings 9.16/9.92 ns. It moves exactly eleven DDR
control cells from the seed-8 placement; every packed logical cell, parameter
and connection is equivalent. Original placement legality and pin legalization
run without bypass. Evidence: `build-ddr-local-legal-ddr-mid-final/manifest.json`
and `build-ddr-route-local-ddr-mid-seed2/manifest.json`. Remaining system setup
shortfall is about 0.253 ns. The worst path now starts at the high-fanout reset
net. Original clock periods are restored and the same DDR signoff limitations
remain. Full workflow and rejected trials: [REROUTE.md](REROUTE.md).


The best **fixed-placement reroute** now reports **97.42 MHz system /
101.68 MHz CPU**, with crossing delays 9.16/9.92 ns. Evidence:
`build-ddr-reroute-restored8-seed2/manifest.json`. All 42,569 cell locations
remain unchanged. The checkpoint import omits automatic clock derivation, so
the original XDC is retained verbatim and identical parent-derived clock periods
are explicitly restored. Final targets are verified at system/CPU 100 MHz and
input/IDELAY 200 MHz; the hashed parent supplies PLL/buffer derivation evidence.
The raw strict report is preserved, including its missing automatic-derivation
log notices and DDR bank warning. This is diagnostic setup timing, not DDR
physical signoff; system timing still misses 100 MHz by about 0.265 ns.

The best complete **pack/place/route** run remains the following seed-8 result.

**100 MHz is not closed.** The current opt-in front-runner is narrow TPU phase
counters + direct CSR reads + parallel masked DDR command selection:
**95.39 MHz system / 100.52 MHz CPU**, seed 8. Related-clock delays are
9.10 ns system→CPU and 9.82 ns CPU→system, against 10 ns budgets.
The full 45-shape and smoke PROFILE, METRICS and DMA records are exactly
unchanged from packed-loads firmware. This preserves CPU IPC and useful
MAC/system-cycle throughput. Evidence:
`build-ddr-seeds-parallel-chooser-rest/seed-8/manifest.json`,
`build-ddr-gemm-parallel-chooser/system/results.json` and
[parallel chooser validation](dram-parallel-chooser/README.md).

```sh
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-goal-new \
  --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul \
  --bus-payload --uart-control --dram-command-buffer --dram-write-buffer \
  --packed-rows --firmware-opt=-O3 --tpu-counters --csr-read-direct \
  --dram-parallel-chooser
```

Use matching arguments for synthesis after current component proof checks.
The eight-seed comparison is complete. The next targeted probe combines
parallel selection with the proven registered refresh/ZQCS timer terminal flag.
The unsupported `get_iobanks`/DCI warning remains: these are diagnostic routed
timing results, not DDR calibration/electrical or hardware signoff. No board
defaults or sibling CPU files are promoted or overwritten.

## Earlier route round (historical)

**100 MHz is not closed.** The best system-clock candidate from this round reaches
**98.91 MHz CPU / 84.54 MHz system**. It also misses the related CPU-to-system
10 ns path by 0.08 ns. All routes retain the unsupported `get_iobanks`/DCI
constraint diagnostic; none establishes DDR calibration or hardware signoff.

| Corrected candidate | CPU MHz | System MHz | System→CPU | CPU→system |
|---|---:|---:|---:|---:|
| Inlined firmware + system-decode | 95.45 | 75.31 | 8.14 ns | 9.54 ns |
| Divider payload + UART control | **98.91** | **84.54** | 9.33 ns | 10.08 ns |
| Direct MUL selection + bank row-hit | 90.17 | 83.47 | 8.79 ns | 10.01 ns |
| Denser placement of control/payload | 81.67 | 71.32 | 11.07 ns | 15.18 ns |
| Interrupt eligibility staging | 87.15 | 83.46 | 10.75 ns | 11.95 ns |
| Packed rows + opt-in firmware | 102.51 | 81.57 | 8.62 ns | 10.13 ns |

These use seed 4, the original XDC and the same nextpnr/chipdb pair. The density
probe changes only HeAP beta from 0.4 to 0.6. The slower combinations are not
promoted over the control/payload candidate. The interrupt-eligibility candidate
passes functional and IPC validation but routes more slowly and is also rejected.

The best candidate is recorded in
`build-ddr-dma-control-payload/board/route-manifest.json`. Its configuration is:

```sh
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-current-new \
  --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul \
  --bus-payload --uart-control --dram-command-buffer --dram-write-buffer
```

Use the same arguments with `synth` and `route` after the required peripheral
and DDR checks. Current scripts reject stale generated sources and proof inputs.
These remain isolated experiments; the default board builder and sibling CPU
sources are not promoted or overwritten, and no FPGA has been programmed.

## Historical CPU baseline before the throughput firmware update

These measurements describe the earlier firmware used to validate timing-only
edits. The current throughput firmware intentionally changes the instruction
mix and DMA counts; the table is retained as historical evidence:

| Workload | Instructions / enabled CPU edges | IPC | System cycles |
|---|---:|---:|---:|
| Fixed multiply benchmark | 4,007 / 4,118 | 0.973045 | Clock-mode dependent |
| DMA smoke, 35 results | 173,078 / 223,294 | 0.775113 | 1,185,342 |
| DMA stress, 162 results | 306,842 / 405,428 | 0.756835 | 2,189,877 |

See [IPC_AUDIT.md](IPC_AUDIT.md) for exact bubble accounting. Branch prediction
is explicitly deferred. CPU IRQ/fault cases and divider arithmetic/cancellation
also pass; the expanded DMA/error suite passes 27 cases.

## Accelerator throughput is a separate issue

[TPU_UTILIZATION.md](TPU_UTILIZATION.md) measures the GEMM calls themselves,
excluding boot and DDR self-test. The dense 8×16×8 call achieves 0.810906 CPU
IPC but takes 419,050 system cycles for 1,024 useful MACs. Average array-busy
time is only 0.03245%; useful PE capacity is 0.007636%. Both DMA and TPU are idle
for 94.05% of the call. This is a behavioral-memory result, not a physical DDR
starvation measurement. Command handling, CPU memory latency, local operand
copying and short-tile fill/drain all matter.

[PACKED_ROWS.md](PACKED_ROWS.md) records the new four-byte operand aperture and
opt-in firmware. Dense GEMM cycles fall 39.6% while its CPU IPC improves from
0.810906 to 0.817015. Aggregate smoke/stress IPC falls, so the default firmware
keeps the legacy operand path and its exact baseline profiles. Packed-row routing passes the CPU-clock target at 102.51 MHz but fails the
system-clock target at 81.57 MHz and CPU-to-system path at 10.13 ns. The earlier best timing numbers above
refer to their saved pre-extension netlist, not the newly extended AXI wrapper.

[FIRMWARE_STATUS_SUMMARY.md](FIRMWARE_STATUS_SUMMARY.md) records faster firmware
variants that lower aggregate IPC on at least one workload. They were not
adopted under the current IPC floor; exact source snapshots remain available.

Earlier buffered-DDR routes predating WRITE-DRAIN are invalid implementation
candidates; see [DDR_NATIVE_WRITE_CORRECTION.md](DDR_NATIVE_WRITE_CORRECTION.md).
The current adapter suites include strict scheduled-write checks. Ethernet
remains a documented future extension, not RTL included in these tests.

## Broader GEMM IPC measurement

[GEMM_SWEEP.md](GEMM_SWEEP.md) compares 45 shapes and 3,022 checked results per
firmware path. GEMM-only pooled IPC (`sum instructions / sum enabled CPU cycles`)
improves from **0.812468 to 0.820446** with packed rows, while GEMM system cycles
fall **42.86%**. The equal-shape mean falls from 0.792186 to 0.784306; IPC improves
on 12 shapes and falls on 33, although all 45 finish sooner. Full-program IPC
includes a different mix of boot/setup/verification work and must not be confused
with this GEMM-only ratio. Packed rows remain opt-in, with the default preserved.

## Retained RV32IM throughput improvements

[FIRMWARE_THROUGHPUT.md](FIRMWARE_THROUGHPUT.md) supersedes the earlier decision
to reject lower-IPC firmware solely on that metric. Under the user's useful-work
per total-system-cycle objective, the retained driver eliminates redundant status
scans and reduces result collection to three commands. With packed rows and
`--firmware-opt=-O3`, whole-test MACs/cycle rise 75.2% over the previous packed
firmware. All 45 shapes also improve GEMM time and IPC: pooled IPC is 0.864774
and equal-shape mean is 0.844598. Legacy operand firmware benefits as well.

The new board firmware synthesizes and routes with the same timing as the
preceding packed-row build: 102.51 MHz CPU, 81.57 MHz system, system-to-CPU
8.62 ns and CPU-to-system 10.13 ns. The full 100 MHz target still fails, and
the unsupported I/O-bank constraint warning remains. Evidence is in
`build-ddr-dma-throughput-o3/board/route-manifest.json`.

## Latest command reuse iteration

[COMMAND_REUSE.md](COMMAND_REUSE.md) records retained packed-firmware command
reuse. Whole-test cycles fall from 15,601,564 to 12,029,963 and useful MACs per
system cycle rise from 0.00462928 to 0.00600368 (+29.7%). GEMM cycles fall 37.4%,
but pooled IPC falls from 0.864774 to 0.825320. Twenty-three shapes finish sooner;
22 smaller shapes regress by at most 3.55%. The complete 45-shape scoreboard,
96/112/113-command buffer boundaries and cached-descriptor read/write error
recovery pass. Legacy mode keeps its exact previous profiles.

Synthesis passes and the flattened hardware is identical to the previous board
except boot RAM contents (generated source path names normalized). No fresh
route is claimed. There is no instruction cache in the core or tested SoC;
firmware executes from synchronous on-chip boot RAM via the uncached sequencer.

## Latest aligned-load iteration

[PACKED_LOADS.md](PACKED_LOADS.md) records retained load-header reuse and guarded
aligned word loads for operand packing. Whole diagnostic cycles fall from
12,029,963 to 11,544,608, giving 4.20% more useful MACs/system cycle. GEMM cycles
fall 8.24% and external data-wait cycles fall 38.5%. Twenty-six shapes improve;
19 regress, up to 7.63% on 1×1×1. Pooled IPC falls to 0.801148. Signed extremes,
unaligned bases, minimum/cached buffer bounds and injected read/write errors pass.

The new exclusive sequencer-state audit shows four states per enabled CPU edge
occupying 78.7% of GEMM cycles; external data wait is 10.6%. These states overlap
DMA/TPU activity and are not added to that separate partition. Both audits are
observation-only and preserve exact firmware bytes/profiles.

Synthesis passes and the flattened hardware remains identical except boot RAM
contents after source-path normalization. No new route or timing closure is
claimed. The legacy firmware path preserves its exact prior profiles.

## Wishbone decode timing experiment: rejected

[wb-decode/README.md](wb-decode/README.md) records an opt-in experiment that
captures region selects alongside the Wishbone address, adding no transaction
or CPU cycles. Temporal induction passes, the CPU/DMA/TPU smoke test preserves
exact profiles, and board synthesis passes. The same seed-4, 100 MHz route
regresses to **99.59 MHz CPU / 78.11 MHz system**, with system-to-CPU 9.30 ns
and CPU-to-system 10.15 ns. It remains disabled and is not promoted.

The retained packed hardware's last routed result is still **102.51 MHz CPU /
81.57 MHz system**, with CPU-to-system 10.13 ns. Latest retained firmware has
only been structurally compared against that hardware, not freshly routed.
The new experiment's system critical path starts at DDR bank-machine timing
readiness and takes 12.8 ns, including 10.9 ns routing. Full 100 MHz timing
closure and DDR hardware signoff remain outstanding; the unsupported I/O-bank
constraint warning persists. Evidence: `build-ddr-dma-wb-decode/board/route-manifest.json`.

## Latest packed-design seed sweep

[SEED_SWEEP.md](SEED_SWEEP.md) records eight fresh routes of the latest retained
firmware netlist with fixed hardware, tools and constraints. Seed 4 remains best
at **81.57 MHz system / 102.51 MHz CPU**, with CPU-to-system 10.13 ns. Seed 7
reaches 81.14 / 102.43 MHz; the system range is 70.20–81.57 MHz. No seed closes
100 MHz, and the I/O-bank warning remains. All input hashes are unchanged.
This supersedes the earlier statement that the latest firmware had no fresh
route; no RTL, firmware or architectural cycle counts changed in the sweep.

## Registered Wishbone active enables: rejected

[wb-active/README.md](wb-active/README.md) records a cycle-equivalent candidate
that registers full per-target CYC/STB enables. Formal induction, exact smoke
profiles and synthesis pass. Matched seed 4 regresses to 68.57 MHz system /
90.62 MHz CPU; seed 7 regresses to 78.38 / 97.73 MHz. The candidate remains
disabled. Retained timing is still 81.57 MHz system / 102.51 MHz CPU.
DDR maintenance control paths dominate the new routes, with 10.7–12.4 ns
routing delay. Full 100 MHz closure remains outstanding.

## Registered refresh timer: not retained

[dram-refresh-timer/README.md](dram-refresh-timer/README.md) records an exact-cycle
registered zero flag for refresh/ZQCS timers. Actual generated RTL equivalence
passes for board periods and boundary cases; three upstream refresh tests,
exact CPU/DMA/TPU smoke profiles and synthesis pass. Seed 4 fails a nextpnr
placement validity check (no Fmax); seed 7 regresses to 75.83 MHz system /
89.13 MHz CPU. The experiment remains disabled. Its critical path now runs
from refresher state to bank-machine command-buffer readiness/register enable,
13.2 ns total with 11.5 ns routing. Retained timing remains 81.57 MHz system /
102.51 MHz CPU; full 100 MHz closure is still outstanding.

## Bank-local command ready: not retained

[dram-local-ready/README.md](dram-local-ready/README.md) records removing the
selected-valid mux from per-bank ready logic. Full eight-bank chooser equivalence,
14 upstream multiplexer tests, exact smoke profiles and synthesis pass. Seed 4
reaches 80.46 MHz system / 107.35 MHz CPU with both cross-clock paths below 10 ns;
seed 7 reaches 74.26 / 98.52 MHz. Both system results regress, so the candidate
remains disabled. Both critical paths now start at system reset and end at
register enables, dominated by 11.0–12.1 ns routing. Reset fanout is a concrete
follow-up target, without timing exceptions. Retained system Fmax is 81.57 MHz.

## UART local acceptance: not retained

[uart-local-accept/README.md](uart-local-accept/README.md) records that the preceding
reset path ended at a UART enable. Factoring UART acceptance away from irrelevant
DDR-ready logic passes exact combinational equivalence, unchanged smoke profiles
and synthesis. Matched seed 4 regresses to 71.24 MHz system / 84.95 MHz CPU;
seed 7 regresses to 80.01 / 89.88 MHz. The candidate remains disabled. Retained
timing is still 81.57 MHz system / 102.51 MHz CPU. Reset gating is unchanged.

## Active 100 MHz goal: mapping and reset-fanout probes

The explicit stage goal is 100 MHz routed SoC timing while maintaining CPU IPC
and useful-work throughput. Two mapping probes on identical retained RTL, firmware
and XDC pass synthesis but regress at seed 4: ABC9 gives 63.26 MHz system /
70.48 MHz CPU; legacy ABC without wide LUTs gives 67.96 / 86.02 MHz. No retiming
is used. Evidence: `build-ddr-map-{abc9,nowidelut}/source-manifest.json` and
`build-ddr-seeds-map-{abc9,nowidelut}/results.json`. Neither is retained.

A placement-guided reset replication probe splits 10,423 reset loads across
14 copies of the existing final FDPE synchronizer stage. A structural audit
checks identical type, INIT and C/CE/D/PRE inputs for every copy, and exact
original-netlist equality after collapsing copied nets. This proves digital
equivalence, not metastability or physical reset recovery/removal. It also
regresses: seed 4 gives 70.50 MHz system / 91.12 MHz CPU; seed 7 gives
76.72 / 98.96 MHz. It is not retained. Evidence:
`build-ddr-reset-replicated/replication.json`,
`build-ddr-seeds-reset-replicated/results.json`. Driver:
`tools/synapse32_reset_replicate.py`. No added reset stage or timing exceptions.

Retained routed Fmax remains 81.57 MHz system / 102.51 MHz CPU. The goal remains
active and incomplete. DDR physical signoff and the unsupported I/O-bank
constraint remain explicit limitations.

## Completed wide-command queue: rejected

[dram-wide-command/README.md](dram-wide-command/README.md) records a two-entry
queue after wide command assembly. All 22 adapter tests pass, including strict
scheduled writes; paired native traffic is identical. Adapter workload cycles
rise 1.94% (7,731→7,881). Both routed seeds regress to about 79.2 MHz system.
The queue is not retained. Behavioral SoC profiles are unchanged but do not
model this physical DDR latency. The active goal remains incomplete.

## Timing-budget placement: not retained

`tools/synapse32_budget_placement_sweep.py` applies nextpnr `--placer-budgets`
to the unchanged retained netlist. Both seed 4 (80.89 MHz system / 96.85 MHz CPU)
and seed 7 (77.89 / 97.41 MHz) regress. Evidence is in
`build-ddr-seeds-budget-placement/results.json`. No clock/constraint/RTL changes.
The next active probe narrows the TPU wrapper's 32-bit phase counters while
proving complete state/output equivalence; it is not yet validated or integrated.

## Narrow TPU counters: promising, full seed comparison underway

[tpu-counters/README.md](tpu-counters/README.md) records cycle-equivalent feed/flush
counter narrowing. N=4 compositional proof passes; smoke and 45-shape GEMM
profiles are exactly unchanged. Synthesis removes 116 flip-flops and 102 CARRY4
cells. Seed 4 improves system Fmax to **85.82 MHz**, with CPU 95.19 MHz; seed 7
reaches 81.22 / 89.49 MHz. Remaining six baseline seeds are in progress. This is
not 100 MHz closure or physical signoff; the candidate remains opt-in.

## Register-file reset ownership: promising, routing underway

[registerfile-valid/README.md](registerfile-valid/README.md) records a register-file
payload RAM with written-bit reset semantics, preserving zero reads, forwarding
and x0. Arbitrary-input architectural equivalence passes. Smoke and all 45 GEMM
shape profiles are exactly unchanged. Synthesis removes 992 resettable flops and
527 LUT6 cells, adding 12 RAM32M cells. Seed 4 is routing; no timing gain is yet
claimed. This is isolated from the TPU-counter candidate for initial comparison.

The full TPU-counter seed sweep is complete: best system Fmax **85.82 MHz**,
CPU **95.19 MHz** on seed 4. Mean system Fmax across eight matched seeds
improves 76.603→77.541 MHz; four seeds improve and four regress.
This is the current opt-in timing front-runner with exact GEMM/IPC profiles,
not 100 MHz closure or DDR physical signoff.

Register-file standalone routes regress: seed 4 is 79.05 MHz system / 97.28 MHz
CPU; seed 7 is 76.12 / 101.34 MHz. The standalone variant is not retained.
Combined with TPU counters, exact smoke and 45-shape profiles still match, but
initial routes (79.96 / 98.80 MHz at seed 4, 84.08 / 82.80 MHz at seed 7) do not
beat the counter-only front-runner. Its remaining six seeds are in progress.

A new `dram-resetless-write` probe removes reset only from unowned wide write
payload bits, retaining the corrected adapter. Temporal induction preserves
valid full words and handshake timing under arbitrary valid/data/ready/reset;
all 22 adapter tests including strict scheduled writes pass. It is being
synthesized with narrow TPU counters; no timing improvement is yet claimed.

The combined counter/register-file eight-seed sweep is complete: best system
85.41 MHz (CPU 93.34 MHz, seed 6), mean system 82.1375 MHz. It is more consistent
than counter-only (mean 77.54125 MHz), but counter-only still has the best joint
route at 85.82 MHz system / 95.19 MHz CPU. No 100 MHz closure yet.

Constant TPU feed-slot decoding proves cycle-equivalent and retains all 45-shape
profiles, but regresses at seeds 4 (80.13 MHz system / 94.55 MHz CPU) and 7
(76.41 / 102.04 MHz); it is not retained. Resetless DDR payloads pass proof and
22 adapter tests but seed 4 regresses to 79.03 / 98.32 MHz; seed 7 is running.

Explicit one-hot DDR bank FSM encoding is the next probe. The initial attempt
to force a synthesis hint did not extract/recode the FSM, so its no-op proof is
explicitly rejected. The replacement generates one-hot codes with correct INIT
and reset values, lowers state decisions to individual bit tests, and passes
complete bank-machine equivalence plus 14 upstream tests at board geometry.
The proof covers reachable one-hot states from initialization/reset, including
arbitrary command/refresh/backpressure inputs, not fault-induced illegal states.
The one-hot bank board synthesized with narrow TPU counters, but its routes
regressed: seed 4 reaches 80.72 MHz system / 93.77 MHz CPU, seed 7 reaches
68.32 / 89.01 MHz. It remains disabled. Evidence is in
`build-ddr-seeds-onehot-bank/results.json`.

Resetless DDR payload seed 7 also regressed, reaching 74.58 MHz system /
92.12 MHz CPU. Both resetless routes are rejected. The front-runner remains
the counter-only seed 4 at 85.82 MHz system / 95.19 MHz CPU, with exact
smoke and 45-shape profiles preserved.

The next physical-flow probe changes only HeAP anchoring weight (alpha 0.04
and 0.16 versus default 0.08), retaining beta 0.4, seed 4, the exact counter
netlist, firmware, clock constraints, and tool/chipdb. Results are pending.

The anchoring probes completed without improvement: alpha 0.04 gives 79.49 MHz
system / 93.95 MHz CPU, alpha 0.16 gives 81.95 / 102.43 MHz, with the latter
still failing CPU-to-system timing at 11.40 ns. Default alpha remains 0.08.
Density probes at beta 0.2 and 0.8 are running on the same counter netlist.

`csr-read-direct` removes the redundant outer CSR-validity gate from the read
mux; validity output and sequential behavior stay unchanged. Arbitrary-state
combinational equivalence passes for all CSR addresses/read enables. Smoke and
all 45 GEMM shapes have exactly equal PROFILE, METRICS and DMA records. The
candidate is synthesizing on narrow TPU counters, with no timing claim yet.

CSR direct read is the new opt-in timing front-runner: seed 4 reaches
**87.60 MHz system / 91.24 MHz CPU**, seed 7 reaches 85.55 / 90.73 MHz.
All 45-shape and smoke profiles remain exactly unchanged. The remaining six
seeds are running. The 100 MHz goal remains incomplete.

Density beta 0.8 also regresses (58.01 MHz system / 83.75 MHz CPU); both
density extremes are rejected. A single alternative-SA-placer probe is running
on the fixed counter-only netlist. The counter + Wishbone predecode combination
has passed smoke and synthesized; its routes are next.

The complete CSR-direct eight-seed sweep has mean system Fmax **84.37125 MHz**
versus 77.54125 MHz counter-only; best remains 87.60 MHz system / 91.24 MHz CPU.
Cross-clock failures remain included in route ranking, including seed 6.
No 100 MHz closure is claimed.

`dram-onehot-refresh` changes only the four-state Refresher encoding and direct
state-bit decoding. Complete board-settings command/state equivalence and all
three upstream refresh tests pass. Smoke is exact; synthesis passes; two routes
are running on the counter + CSR front-runner.

Counter + Wishbone predecode routes are rejected: seed 4 76.03 MHz system /
91.90 MHz CPU, seed 7 82.30 / 101.16 MHz. One-hot refresher also regresses:
seed 4 77.10 / 98.38 MHz, seed 7 77.44 / 94.38 MHz. These remain disabled.

HeAP timing weight 30 on the CSR front-runner gives 85.48 MHz system /
98.57 MHz CPU, below default-weight best. The exact logic/firmware/constraints
are unchanged, and the routed JSON confirms weight 30 was used. The alternative
SA placement trial was terminated after about 12 minutes with estimated wire
length still above 10 million versus roughly 0.7–0.8 million for HeAP. It has
no routed Fmax result; do not treat it as a completed timing measurement.

CSR + register-file RAM + narrow counters preserves exact smoke and 45-shape
profiles, but seed 4 reaches only 74.93 MHz system / 99.88 MHz CPU; seed 7
reaches 86.06 / 103.42 MHz. Seeds 6 and 2 are running. Parallel masked DDR
command selection passes complete chooser equivalence and 14 upstream tests,
with exact smoke and passing synthesis; its first two routes are running.
Factored CSR validity ranges pass exhaustive read/validity equivalence and
smoke; synthesis and the 45-shape sweep are in progress.

Parallel masked DDR command selection is the new opt-in routed front-runner:
seed 4 **88.20 MHz system / 98.59 MHz CPU** (joint margin −0.118), seed 7
82.28 / 105.76 MHz. Complete chooser equivalence and 14 upstream tests pass;
smoke is exact. The full 45-shape check and remaining seed comparison are next.
The 100 MHz goal remains incomplete, with physical DDR signoff limitations.

The parallel-selector 45-shape check is complete with exact PROFILE/METRICS/DMA
equality. CSR validity factoring also preserves profiles, but routes regress to
74.98/89.41 MHz (system/CPU, seed 4) and 74.31/98.39 MHz (seed 7); it is rejected.
The combined parallel-selector + registered timer proof contracts match actual
patched source and pass 17 combined upstream tests. Smoke is running before
synthesis. This combination specifically targets the front-runner's path from
the 27-bit ZQCS timer zero detection through bank control.

The parallel-selector seed 2 route improves the front-runner to **88.75 MHz
system / 96.11 MHz CPU**; both crossing delays pass 10 ns (8.81/9.66 ns).
Weight 3 regresses to 82.45/85.69 MHz; default weight stays unchanged.
CSR/register-file seeds 6 and 2 regress to 80.40/88.68 and 78.43/96.15 MHz.

The parallel-selector + registered timer combination passes 17 combined tests,
exact smoke, and synthesis. Its routes are running. A new `tpu-spm-valid`
probe uses per-cell ownership bits to preserve zero-after-reset A/B scratchpad
reads while permitting payload RAM inference. Full N=4 compositional wrapper
equivalence passes, including partial loads, reset, array inputs and result
readout. Smoke is running on CSR-direct + parallel-selector hardware.

The completed parallel-selector sweep produces a substantial new best:
**95.39 MHz system / 100.52 MHz CPU at seed 8**, with crossings 9.10/9.82 ns
and joint margin −0.0461. All fixed input hashes remain unchanged. The system
period is about 10.48 ns, still short of 100 MHz by about 0.48 ns. The full
45-shape profile is unchanged. Routing-only probes preserve this exact packed
logic and placement while removing routing attributes and varying router seed.

The selector/timer combination reaches 90.93 MHz system / 106.83 MHz CPU at
seed 4, but CPU→system is 10.03 ns. Seed 7 is still running.

The pre-routing seed-8 checkpoint reproduces all 42,569 cell locations exactly
and preserves source hashes. Post-routing JSON could not be imported for
routing-only trials because of a constant LUT A6 pin; those two attempts have
no timing result. A new probe uses the verified pre-routing checkpoint instead.

TPU scratchpad ownership passes the complete 45-shape exact-profile check.
Synthesis removes 448 resettable FDCEs but adds 512 FDREs and infers no additional
RAM32M cells; it reduces reset loading, not mapped storage area. Routes remain
in progress. The best complete route is still 95.39 MHz system / 100.52 MHz CPU.

Scratchpad ownership routes are rejected: seed 4 82.93 MHz system / 105.76 MHz
CPU; seed 8 86.15 / 94.30 MHz. Timer-combination seed 8 also regresses to
78.53 / 110.01 MHz. Selector-only seed 8 remains best at 95.39 / 100.52 MHz.
The verified pre-routing checkpoint imports successfully and routing is in
progress. Seeds 9–16 are running on the exact selector-only netlist.

The extra full-placement seeds 9–16 do not improve joint timing. Seed 13's
96.20 MHz system figure is limited by a 10.84 ns CPU→system crossing, so it
does not replace the best full route. Its checkpoint reproduces all 42,569
locations exactly and is being rerouted as an alternative placement.

Restored fixed-placement seed 7 gives 93.07/103.86 MHz system/CPU; A* weight
1.0 at seed 4 gives 96.24/102.31 MHz with a 10.09 ns CPU→system crossing.
The best joint diagnostic result remains 96.80/99.16 MHz with crossings
9.16/9.89 ns. New router-seed and center-bias trials are in progress.

Restored seed 2 improves joint timing to **97.42 MHz system / 101.68 MHz CPU**,
with crossings 9.16/9.92 ns. This is the latest best diagnostic reroute.
Default router seeds 1, 3, 6 give 96.23/100.30, 95.79/98.88, 93.07/102.30 MHz
(system/CPU), respectively. Center bias zero at seed 4 gives 93.07/101.68 MHz.
The seed-13 placement reroute reaches 97.99 MHz system but is limited by
96.15 MHz CPU and a 10.60 ns crossing, so it is not a better whole-SoC route.

An isolated router binary now stable-sorts pending sinks by timing criticality
within each net. This changes only routing order. Every other linked object,
including timing/architecture code, is byte-identical; original sources, objects
and binary are unchanged. Build proof: `/tmp/tiny3tpu-nextpnr-critical-sinks/build-manifest.json`,
tool SHA256
`b06f164640e9c8b7b85877bb0c1e8b1dacb6a21b99258158d4c81ae8ebf2246f`.
Its seed 2/4 comparison routes completed at 93.07/101.68 and 95.10/101.68 MHz
(system/CPU), with exact fixed placement and restored original clock periods.
Both regress, so the isolated router is rejected. Original-router seed 5 gives
95.39/100.72 MHz; the best remains restored seed 2 at 97.42/101.68 MHz.

The [DDR selector-bus experiment](carry-guidance/SELECTOR_BUS.md) now has four
completed, independently audited packed-logic routes. The first two-LUT
factorization hid a comparison dependency in its supposed early term and
reached 12.131 ns. Complete two-comparison cofactors reach 11.745 ns; reserving
final LUT sites first reaches 11.836 ns. A three-control encoding reduces the
added logic to 48 LUTs and reaches 11.072 / 11.072 / 11.372 ns. Its selector
group improves to 10.374 ns and failing endpoint/domain pairs fall to 262,
but DDR pipeline CE becomes worse, so it does not replace the retained
11.038 ns worst probe. All changes are combinational, with exhaustive and
actual primitive SAT proofs; no fresh workload or whole-RTL synthesis is
claimed. Stock aggregate stage 17 verifies 31 fresh routes, 11 fixed-layout
results, two reanalyses and 1,712 hashes. Every full timing gate still rejects.
An exact lossless checkpoint replay of the encoded candidate passes; a
compatible old-route reuse and an additional proved AW-ready LUT collapse
are being tested separately.

Stock aggregate stage 18 verifies 31 fresh routes, 13 fixed-layout results,
two reanalyses and 1,779 hashes. The new best stock diagnostic and its tradeoff
are recorded at the top of this status file; the full timing gate still rejects.

The next two DMA guard factorizations are now proved and routed. The first
changes FF77358 CE from 10.954 to 10.520 ns, but whole-design probes regress to
10.720 / 10.720 / 11.222 ns. Factoring both parallel range branches gives
**9.233 ns** at that endpoint; length_active/rx_active disappear from the
failing groups, and total failing endpoint/domain pairs drop from 337 to 275.
Its whole-design probes are 10.855 / 10.855 / 10.955 ns, now limited by DMA
status FIFO length input. Native reports are 91.28 MHz system / 101.25 MHz CPU.
The combined proof covers 13,312 cut cases and 18 outputs using actual Xilinx
LUT primitives, adds three LUTs beyond the selector encoder, and adds no state
or execution cycles. Both independent audits pass; both timing gates reject.
Stock aggregate stage 19 verifies 31 fresh routes, 15 fixed-layout results,
two reanalyses and 1,846 hashes. Best worst probe remains 10.954 ns. Exact
lossless replay of the dual-guard candidate passes; compatible-route reuse
is being measured before selecting further changes.

Stock aggregate stage 20 verifies 31 fresh routes, 16 fixed-layout results,
two reanalyses and 1,877 hashes. The dual-guard route reuse improves all three
probes to 10.720 / 10.720 / 10.841 ns and reduces failures to 188 endpoint/domain
pairs. Its independent audit and complete imported-route resource check pass;
its full timing gate rejects. The next candidate composes the already-proved
AW-ready LUT collapse with both DMA guard changes. All 13,376 cut cases and a
19-output actual primitive SAT proof pass; its fixed-placement route is running.


Stock-column aggregate stage 22 verifies 31 fresh routes, 21 fixed-layout
results, two reanalyses and 2,042 hashes. The retained diagnostic is the linear
counter encoding with compatible-route reuse: 10.781 ns in all three probes.
The [reset cofactor experiment](carry-guidance/RESET_CHOICE.md) improves its local
bridge CE path but its initial full route regresses; it is not selected.
Full physical timing remains unaccepted.


Stage 23 adds the reset candidate with compatible-route reuse: 31 fresh routes,
22 fixed-layout results, two reanalyses and 2,067 verified hashes. Its expanded
worst ties 10.781 ns, while native partial CPU timing reaches 100.53 MHz. The
expanded CPU-to-system path still fails 10 ns; no full timing acceptance follows.
All 19,098 imported route resource sets are unchanged. See the reset record.


Stage 24 verifies 31 fresh routes, 23 fixed-layout results, two reanalyses and
2,100 hashes. The first read-response cofactor route passes integrity but
regresses to 11.384 ns in all probes and is rejected. A four-LUT collapsed
revision passes exhaustive/primitive proofs and all four negative checks;
its routing result is pending. The retained worst diagnostic remains 10.781 ns.


Stage 25 verifies 31 fresh routes, 24 fixed-layout results, two reanalyses and
2,133 hashes. The collapsed read-response candidate passes integrity but reaches
11.034 / 11.034 / 11.139 ns and is not selected. A two-late-control encoding uses
two early LUT6s and a final LUT4, passes 1,024 cut cases and primitive SAT, and
is routing. No new timing result is claimed for it.


Stage 26 verifies 31 fresh routes, 25 fixed-layout results, two reanalyses and
2,174 hashes. The single read-response encoder passes integrity but reaches
10.901 / 10.901 / 11.001 ns. Its exact replay passes. The eight-branch vector
mapping passes 8,192 branch cases, joint eight-output primitive SAT across 52
shared cuts, and upstream early-input independence checks. Routing is pending;
no timing improvement is claimed for the vector mapping yet.


Stage 28 verifies 31 fresh routes, 27 fixed-layout results, two reanalyses and
2,267 hashes. The vector encoder passes integrity at 10.792 / 10.792 / 10.892 ns;
its read-response target improves to 10.407 ns. The subsequent DMA placement
variant passes full routing, exact logical equality and all 47 planned moves,
with native 94.38 MHz system / 97.99 MHz CPU. Expanded qualification is pending;
it does not yet replace the retained 10.781 ns diagnostic or establish closure.


Stage 29 verifies 31 fresh routes, 28 fixed-layout results, two reanalyses and
2,293 hashes. The retained DMA-near vector route passes integrity at
10.507 / 10.507 / 10.595 ns. A proved write-ID guard and a separate read-response
capture placement variant are routing. Full physical timing remains unaccepted.


Stage 30 verifies 31 fresh routes, 30 fixed-layout results, two reanalyses and
2,362 hashes. The retained guard/capture placement passes integrity at
10.517 / 10.517 / 10.590 ns, with 136 failing endpoint/domain pairs. Its selected
DMA status, write-ID enable and read-response capture endpoints are all below
10 ns in the same candidate. The 16-pair selector placement routes legally but
its native timing regresses; expanded checks are pending. No full-SoC timing
acceptance or promotion has occurred.


Stage 31 verifies 31 fresh routes, 31 fixed-layout results, two reanalyses and
2,390 hashes. The register-only selector move passes integrity but regresses
to 10.779 / 10.779 / 11.139 ns. A shared-main-enable encoding passes 256 cases,
primitive SAT and corrupted-INIT negative checks. Its baseline and a separate
51-cell selector-feedback/encoder placement variant are routing. Neither has
a timing result yet; the retained worst diagnostic remains 10.590 ns.

Stage 32 adds the main-CE encoding and selector-feedback placement audits.
Both pass functional/placement integrity but miss 10 ns: 10.629 / 10.629 /
10.989 ns and 10.787 / 10.787 / 10.934 ns respectively. Local targets improve
to 9.102 ns (main CE) and 9.755 ns (selector group), with no added cycles.
The hash-checked aggregate now has 31 fresh routes, 33 fixed-layout results,
2 reanalyses and 2,461 hashes. The retained best remains 10.517 / 10.517 /
10.590 ns; no physical timing acceptance or promotion.

The next local AR-ready replica passes proof and routing, but expanded probes
remain 10.855 ns with 139 failing endpoint/domain pairs. Its worst path is
reset through the accelerator transport response-code enable. Final integrity
is pending. A separately proved DMA FIFO reset cofactor is entering routing;
a transport-enable cofactor is being proved. See carry-guidance/MAIN_CE.md.

Stage 33 verifies 31 fresh routes, 35 fixed-layout results, 2 reanalyses and
2,539 hashes. AR-ready and FIFO-reset routes pass integrity at 10.855 ns and
10.818 ns respectively. The FIFO target itself is 9.109 ns. The following
transport-reset route has probes 10.494 ns and target CE 7.690 ns, but its
final integrity remains pending. CPU branch-control collapse passes proof and
is routing. No full timing acceptance or promotion.

Stage 34 verifies 31 fresh routes, 36 fixed-layout results, 2 reanalyses and
2,569 hashes. The transport-reset route passes integrity at 10.494 ns in all
probes and becomes the retained stock-column diagnostic. No physical timing
acceptance or promotion.

### Continued branch, capture and count-flag experiments

The current-layout branch carry/decode cuts pass 2,048 cut cases and actual
primitive SAT. The targeted jump-address FF59993 D path reaches **9.730 ns**,
but the complete route remains **10.653 / 10.653 / 10.753 ns**. Two subsequent
equivalent data-LUT replicas retain the original capture registers and reach
**10.557 ns in all probes**, with FF68660 D at **9.700 ns**. Both final integrity
audits pass; neither replaces the retained **10.494 ns** diagnostic.

A new DMA nonzero-count implementation adds **two redundant internal FDREs
and five LUTs**, with unchanged original counter registers and execution
latency. Each flag tracks the OR of one counter clock-enable group on the
same edges. The original carry predicate equals OR16 under primitive SAT;
the flag invariant passes bounded and inductive actual-primitive proofs from
the existing zero initialization. A deliberately wrong flag CE fails proof.
Its full route and expanded timing assessment are pending. These are packed
implementation experiments, not fresh RTL synthesis or workload simulation;
parent workload evidence is preserved compositionally. All physical coverage
limitations and the open 100 MHz gate remain.

The DMA count-flag route now passes final integrity at **10.391 ns in all
three expanded probes**, with native **96.36 / 97.99 MHz** system/CPU and
**94 failing endpoint/domain pairs**. The flag registers themselves reach
**9.412 ns** in the symbolic-0.1 ns carry probe. This becomes the retained
stock-column diagnostic, superseding 10.494 ns without physical acceptance.
The next experiment collapses the three LUT stages feeding DSP A18 using
exact Boolean equivalence; no extra pipeline stage is introduced.

The DSP input-decode collapse passes 88 local cut cases and joint three-output
primitive SAT, including a rejected corrupt-output control. It closes the
targeted CPU DSP path to **9.316 ns**, but global probes remain **10.392 ns**;
final integrity passes with 80 original-cell moves. The 10.391 ns count-flag
route remains retained. Stage 11 revalidates 24 candidates and 1,542 hashes.

The subsequent DMA strobe reset cofactor passes BDD and primitive SAT across
10 independent cuts, adds four LUTs and no execution cycles, and rejects a
corrupted-output proof. Its full route passes; expanded analysis is pending.
A CPU-to-system synchronous-reset path at 10.315 ns is being simplified next.
The TPU output path at 10.224 ns includes a 5.4 ns combinational DSP arc and
2.565 ns DSP-to-LUT route; no accelerator pipeline/state change has been made.

### Consolidated control fixes and TPU placement

The DMA reset cofactor closes the strobe group to **9.162 ns**, though its
route is globally 10.557 ns with 118 failing endpoint/domain pairs. CPU
synchronous-reset collapses then pass 176 local cases and joint primitive
SAT (corrupt output rejected), leaving every checked input of FF215389 at
or below **9.463 ns**. That layout has **91 failing pairs** and 10.620 ns
worst expanded probes. Both final integrity audits pass.

Moving only the unregistered TPU multiplier at big core 1, PE row 0/column 0
from DSP48_X2Y68 to the legal free DSP48_X2Y60 site reduces the count to
**52 failing pairs**, with **10.557 ns** in all expanded probes and native
**94.72 / 101.25 MHz** system/CPU. Its final audit passes with 86 original-cell
moves, exact logical ports and unchanged execution latency. TPU output
worst delay falls from 10.224 ns to **10.084 ns** at a different multiplier.
This is the fewest-failing-pairs working candidate; the best-period retained
diagnostic remains the count-flag route at **10.391 ns**. These are distinct
layouts, not combined measurements. A second placement-only trial moves
the remaining TPU multiplier from DSP48_X2Y48 to free DSP48_X2Y52.

No physical timing acceptance, firmware change, fresh workload simulation
or RTL promotion is implied. The original two redundant count flags remain
proved state; subsequent edits add no state or execution cycles.

The second TPU placement passes integrity but is rejected: **10.658 ns**
all probes, **93 failing pairs**, and TPU output still **10.080 ns**. The
NOR8-only DDR macro rewrite passes all 256 input cases, actual primitive SAT,
and negative constant/driver controls. With the second DSP move undone,
its completed integrity audit reports **10.941 ns** all probes and **170
failing pairs**. Ready0 only improves locally to 10.503 ns; bank timing
control paths dominate the regression. Neither experiment replaces the
10.391 ns best-period or 52-failing-pair working layout.

The next bounded experiment is recorded in `carry-guidance/NEXT_DDR_MACRO.md`: return
to the 52-pair layout and encode the three functions selected by the next
DDR mux's five early inputs. Only its exploratory truth table exists so far.
Stage 14 revalidates **30 completed candidates and 1,744 hashes**, including
these two rejected routes. Physical 100 MHz closure and all physical
coverage gates remain open.

### DDR control encoding and remaining bank decoders

Ready-macro encoding passes all 256 input cases, primitive SAT, and negative
code/constant controls. It reduces ready0 to **10.137 ns**. Its full route is
**10.620 / 10.620 / 10.714 ns** with 97 failing pairs. Removing two irrelevant
encoder inputs preserves proof and gives **10.620 ns** all probes with 94
failing pairs. Both final integrity audits pass; neither replaces a retained
layout. No state, clock period or execution-cycle changes are introduced.

Collapsing the seven remaining bank valid decoders uses **112 local cases
and joint seven-output primitive SAT**, preserving each paired FF and its
original placement. Final integrity passes at **10.539 ns** all probes, with
95 failing pairs; checked DFI p1/p2/p3 address paths now max at **9.743 ns**.
The worst remaining path is DDR read-valid9. Its matching encoded mux and
two final capture OR8 rewrites pass 256 and 512 cases respectively plus
primitive SAT and rejected constant/output controls. A branch-predicate
collapse targeting 17 exception-data endpoints is being composed with them.
These are packed implementation experiments; workload evidence remains
inherited via proofs, with no fresh firmware simulation or RTL promotion.

### Dead macro cleanup and a proved next-step predicate

The combined read-valid encoding, two capture OR8 trees and branch-predicate
collapse pass their proofs, but their route regresses to **11.469 ns** all
probes (native 87.19/102.70 MHz). Final integrity passes; not selected.
The read-valid OR partition and scattered replacement LUT placement are
identified contributors to this regression.

The next cleanup corrects the OR partition (256 cases and primitive SAT),
removes **24 structurally proved unobservable combinational cells** and 24
unused netnames, and colocates 10 replacement LUTs in the freed sites.
Tests reject an added register/top-port observer, state-cell deletion and
corrupted OR output. All remaining logical ports, all state, and requested
placements pass final integrity. Expanded probes improve to **10.749 ns**,
with **88 failing pairs**, native **93.03/101.25 MHz**. This still does not
replace either retained layout. No clock period or execution cycles change.

A same-edge refresher predicate is now proved feasible using actual FDRE/
FDSE primitives, including INIT=1, synchronous set and source CE hold.
Its four source register inputs max at **4.535 ns** in the traced probe.
Wrong INIT, ignored CE hold and ignored reset each fail proof. This is
**not yet a packed SoC edit or routed result**; the exact implementation
and validation requirements are in `carry-guidance/NEXT_REFRESHER_FLAG.md`.
The active goal and all physical timing gates remain open.

### Same-edge refresher flag implementation (final integrity passed)

Stage 15 aggregate passes: 35 completed candidates, 1,983 dependency hashes,
retained best expanded interval 10.391 ns in all three probes. This is still
an unqualified setup diagnostic; the full timing gate is false.

`build-grade2-refresher-flag/patch.json` now implements the previously proved
predicate on the cleanup parent. It reuses LUT217672 as a LUT6 of the four
source D inputs plus CE3 and held Q3, and adds one FDSE INIT=1 with the same
clock and synchronous set. Flag Q drives the original predicate net. The
four source registers remain unchanged; no execution cycle or LUT is added.
The candidate has three redundant internal flags including the two inherited
DMA count flags. Actual primitive bounded and inductive proofs pass. Six
packed implementation corruptions are rejected. An observer audit proves
all 330 downstream endpoint ports are synchronous on the same system clock;
cross-clock and top-port observer negative controls are rejected.

The full seed-5 route passes normal legality, routing, logical-port and
requested-placement comparisons. Native system/CPU results are 93.55/100.53
MHz. Expanded analysis and final integrity pass at 10.689 ns in all three
probes, with 76 failing endpoint/domain pairs. Its new flag input maximum
is 5.482 ns. This candidate is not selected or promoted. No fresh RTL synthesis or
workload simulation has been claimed.

### Same-edge timer flags: new retained diagnostic best

All three flag candidates pass complete final integrity, identical seed-5 /
100 MHz constraints, and actual-primitive same-edge induction. No execution
cycles are added. Source initialization, synchronous set/reset and CE behavior
are bound to the packed circuit. Corrupted flag initialization, ignored reset,
and incorrect constant drivers fail SAT. Downstream observer checks reach
only same-clock synchronous FF inputs and reject cross-clock/top-port probes.

| Candidate suffix | Expanded probes (ns) | Native system / CPU MHz | Failing endpoint/domain pairs | Original-cell moves |
|---|---|---|---|---|
| refresher-flag | 10.689 / 10.689 / 10.689 | 93.55 / 100.53 | 76 | 92 |
| timer-zero-flag | 10.634 / 10.634 / 10.634 | 94.04 / 101.25 | 64 | 93 |
| timer-mid-zero-flag | **10.358 / 10.358 / 10.358** | **96.54 / 100.53** | **44** | 94 |

The new retained diagnostic is `build-grade2-timer-mid-zero-flag-route`.
It improves both the old best period (10.391 ns, DMA count flags) and the
old fewest failing pairs (52, CPU-reset/TPU-DSP-near layout). Those earlier
artifacts remain intact. This is diagnostic selection, not RTL promotion or
physical timing acceptance. All three probes still exceed 10 ns.

The refresher, first timer and second timer flag input maxima are respectively
5.482, 5.792 and 5.873 ns in their corresponding routed candidates. The two
timer rewrites each replace a MUXF8 root with a next-predicate LUT3 and add
one LUT6 plus one FDRE; old mux children are retained pending guarded cleanup.
The final candidate contains five redundant flags total: two inherited DMA,
one refresher, and two timer flags. Original CPU execution state is unchanged.

The new worst path starts at bank4 address FF77903 Q and ends at read-valid9,
10.358 ns. Other outstanding groups include CPU jump-address (10.324 ns),
DDR read-beat-offset (10.318 ns), ready0 (10.297 ns), and signed-branch-less
(10.287 ns). The previously critical timer-group decode is no longer the
worst source. Parent workload/firmware evidence is inherited through the
proof chain; no fresh RTL synthesis or workload simulation is claimed.

A follow-up guarded cleanup removes 12 further unused timer mux children
and colocates the two timer flags and four LUTs in SLICE_X120Y49. The one
existing DFF there is FF66869 and has the same input-netlist CK=156059,
SR=138579 and constant CE as the flags. Input and routed JSON bit namespaces
must not be compared numerically. The cleanup's full route and final integrity pass, but its 10.614 ns
expanded result (50 failing pairs) regresses and is not selected. A further
two-macro capture encoding also regresses: 10.556 / 10.556 / 10.649 ns,
63 failing pairs, native 93.91/97.32 MHz, final integrity PASS. The retained
10.358 ns / 44-pair candidate remains best. The common predicate across
all 14 remaining capture macros and a paired [4,5,6] seed comparison are
documented in `carry-guidance/NEXT_CAPTURE_SHARED_PREDICATE.md`. These next
steps have not been implemented or run. All physical timing gates remain open.

### Stage 16 aggregate and next-step proof

`build-toolchain-recovery/iterations-summary-stage16.json` passes with
**40 completed candidates and 2,204 verified hashes**. Best expanded probes
are **10.358 / 10.358 / 10.358 ns**; the full timing gate remains false.
All five new routes, their final audits, negative controls and synchronous
observer checks are complete. No routing or aggregate job is left running.

The next global common-predicate form has **14 actual-primitive SAT proofs
and 28 negative SAT checks**, all passing in
`build-grade2-capture-shared-predicate-feasibility/manifest.json`.
It is **not yet a packed SoC implementation or a routed result**.
Continue with `carry-guidance/NEXT_CAPTURE_SHARED_PREDICATE.md`, using the
retained timer-mid-zero parent. The paired [4,5,6] seed set is predeclared;
no new seed4 or seed6 route has run. No promotion has occurred.
