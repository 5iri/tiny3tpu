# Shared main enable and selector feedback placement

Latest retained stock-column diagnostic: **10.358 ns in all probes**,
**44 failing endpoint/domain pairs**, native **96.54/100.53 MHz** system/CPU.
The carry-input inline candidate ties that period with 51 failing pairs;
branch-decode placement has 43 failing pairs at 10.411 ns. Local jump-address
and branch-comparison input groups now reach 9.104 and 9.247 ns respectively.
The paired [4,5,6] comparison is complete: the carry-inline candidate regresses
on mean and worst interval. The broader 394-LUT inline closes the checked CPU
clock-domain paths but still misses system timing at 10.502 ns. See
`NEXT_WRITE_ADDRESS_CARRY_CHOICE.md` for the current DDR iteration. Full timing acceptance remains false. The record
below is chronological history.

The selector-register-only move passes integrity but regresses to **10.779 /
10.779 / 11.139 ns**, limited by FF75216 CE. The path traverses LUT217104 and
LUT233914, with an approximately 2 ns intermediate enable net. This layout is
not selected; the retained result remains 10.590 ns.

Those two LUTs have eight cut inputs. Three late signals are command-enable,
read-address-change and write-address-change. The other five inputs select only
five functions of the late signals: 0, 170, 175, 187 and 255. The chosen codes
are 0, 1, 3, 5 and 4. Three early encoder LUTs have supports 4, 3 and 4; one
final LUT6 receives their outputs and the three late signals. The upstream
independence walk terminates only at registers/constants. All 256 cut cases and
actual primitive SAT pass. Corrupted encoder/final INITs each fail primitive SAT.
The old inner LUT remains for its other consumers. No state or execution-cycle
changes. The completed route and target-path measurements are recorded below.

The selector-register move also exposes a feedback path at 10.555 ns:
selector FF -> LUT217096 -> LUT217094 -> LUT217093 -> early encoder -> final
selector LUT -> FF. Its nets repeatedly cross between Y105, the original Y129
region and the comparison/control region near Y79. The separate
`build-grade2-selector-logic-near` variant moves the three feedback LUTs and
all 48 early encoder LUTs alongside the relocated capture registers, into
Y101–110. It preserves all logic, register parameters and clock controls.
`build-grade2-selector-logic-near-route` completed normal legality, full routing
and complete logical comparison.

These remain packed-netlist experiments composing parent workload evidence
with combinational proofs. No fresh workload simulation or whole-RTL synthesis
is claimed. Generic/carry delays, clock skew/hold, reset recovery/removal and
DDR IO remain unvalidated. No full-SoC timing acceptance or promotion.


The main-CE route passes full routing and exact logic/placement. Its probes are
**10.629 / 10.629 / 10.989 ns**, native 91.00 / 97.32 MHz; it is not selected.
The targeted FF75216 CE improves to **9.102 ns**, but AR-ready becomes the worst
path through a different consumer of shared decode LUT217104, LUT233793.

The feedback/encoder placement variant also passes full routing and exact
logic/placement, with native 91.46 / 97.99 MHz. Expanded probes are **10.787 / 10.787 / 10.934 ns**. The selector group is
**9.755 ns**, but DMA output FIFO WE remains **10.787 ns** and AR-ready
dominates the conservative probe. Final integrity passes with 69 original-cell moves; the gate rejects closure.

A local AR-ready replica passes 256 exhaustive cases and actual primitive SAT. It duplicates LUT217104 exactly,
changes only LUT233793's shared-enable input to the identical new output, and
places that replica near LUT233793. The original decode remains for its other
consumers. This preserves cycle behavior. Full routing and exact logic/placement checks
pass, with native system / CPU diagnostics **92.12 / 97.99 MHz**. Expanded
probes are **10.855 / 10.855 / 10.855 ns**, with 139 failing endpoint/domain
pairs. The worst path is now transport response-code CE, through reset and
five LUT levels. This is not a timing-qualified result.

The next candidate cofactors reset out of the five-LUT DMA output FIFO WE
cone. Its 13 cuts cover 8,192 Boolean cases. Six early LUTs compute the reset
cofactors and a final LUT3 selects with reset; no state or latency is added.
The first proof SAT passed but its patch JSON is empty and unusable. A new
version writes compact JSON to a separate output directory; the incomplete
artifact is retained and is not accepted as proof or used for routing.

The compact FIFO patch now passes all 8,192 cases and primitive SAT. Its
corrupted final INIT is rejected by SAT. The separate fixed-layout route is
running. A following candidate applies the same reset cofactoring to the
seven-node, 13-cut cone of LUT233414 feeding transport response-code CE.
The two proofs retain separate roots and recursively verify their common base.

The AR-ready final integrity passes (69 original-cell moves); the 10.855 ns
result remains rejected. The FIFO cofactor route also passes exact logic and
placement, native 92.44 MHz system / 97.32 MHz CPU. Expanded checks are running.
The transport cofactor passes 8,192 cases and primitive SAT, adding seven
early LUTs; corrupted final INIT is rejected. Its fixed-layout route is running.

The CPU exception-tval path in the AR-ready candidate is 10.530 ns. It passes
through LUT220968 and LUT221081, whose combined function has only six distinct
inputs. A new candidate collapses those two levels into one LUT6, retaining
LUT220968 for other consumers. The candidate composes the transport/FIFO proofs
and is being checked; no routing or throughput improvement is claimed yet.

An observational scan of the AR-ready route finds 17 adjacent LUT pairs on
near/failing setup paths whose combined inputs fit a LUT6. The candidate list
is `build-grade2-ar-ready-replica-route/collapse-candidates.json`; it derives
from hash-checked node traces and makes no predicted timing-gain claim. Some
cones overlap the reset rewrites or each other and must be re-evaluated against
the actual composed candidate before any further transformation.

The FIFO cofactor final integrity passes with probes **10.818 / 10.818 /
10.818 ns**. Its targeted output FIFO `.0.4/DPR2_0` WE is **9.109 ns**, down
from 10.787 ns in the selector-feedback layout (these are successive routed
experiments, not an isolated proof of physical speedup). The transport route
passes exact logic/placement, native **95.29 / 97.99 MHz**; expanded checks
remain pending. The CPU collapse passes all 64 cases and primitive SAT, and
its corrupted final INIT is rejected. Its route is running.

Native CPU timing still reports 97.99 MHz on the transport candidate. That
path is in the divider: remainder comparison, quotient-select, conditional
negation carry chain, then two result-control LUTs into FF67051. Its native
report is retained separately; native symbolic carry arcs and the expanded
Boolean-support-normalized graph are different diagnostics. Neither is a
validated physical carry delay model. The final two LUTs have ten combined
inputs and cannot be directly collapsed into a LUT6. No extra divider cycles
or pipeline stages have been added.

Expanded transport probes are **10.494 / 10.494 / 10.494 ns**, with 137
failing endpoint/domain pairs. The targeted FF59914 CE is **7.690 ns**.
Final integrity is still pending, so this has not replaced the retained best.
The worst remaining endpoint is write-data capture FF68661 D: its data driver
LUT229059 is at SLICE_X130Y132, while the capture is at SLICE_X130Y40/C5FF.
The 4.2 ns final route dominates the path. Any capture move must preserve its
CK/CE/SR controls and consider its outgoing data route; no move has been made.

A bounded multi-output collapse candidate is now being proved against the
completed CPU-collapse proof. It re-evaluates the 17 observed LUT pairs against
the composed graph, skips already replaced roots or cones wider than six
inputs, checks every local truth table and then jointly proves all changed
outputs with actual primitives. Its parent is a SHA-256-checked file reference
to avoid duplicating hundreds of megabytes of nested proof JSON. No parent
evidence or timing model is modified.

The transport final integrity now passes with 71 original-cell moves. Its
10.494 ns worst diagnostic becomes the retained stock-column result. This is
a 0.096 ns diagnostic improvement, not a robust seed or physical closure
claim. The following CPU-collapse route passes exact logic/placement and
reports **93.48 MHz system / 101.25 MHz CPU**; expanded checks are pending.

The bounded collapse proof passes: 13 changed outputs, 384 local exhaustive
cases and joint primitive SAT. Four observed pairs are skipped after checking
the actual composed graph. The CPU-collapse route's expanded probes are
10.620 / 10.620 / 10.697 ns, despite its native 101.25 MHz CPU result; final
integrity is pending and it does not replace the retained system result.

The 13-output proof also rejects a corrupted output INIT. Two fixed-layout
routes are now running: the LUT collapses alone, and the same proved logic
with FF68661 moved from SLICE_X130Y40/C5FF to SLICE_X129Y86/AFF. The middle
placement aims to balance incoming/outgoing data routes; it preserves CK, CE,
SR, D, Q and all register parameters. The destination has no FF, carry, mux
or LUTRAM in the effective layout; actual nextpnr legality remains required.

The original proof completed successfully. Profiling near its end observed
709 sampled stacks in cyclic GC over nested JSON trees. Separate v2 tools
disable cyclic GC without changing the proof algorithm; source comparison
passes and normal reference counting remains enabled. A separate v2 proof
replay is running. No incomplete or interrupted proof is used for routing.

Toolchain interruption: the temporary source/build/database trees and active
processes disappeared before the two new routes produced output. The separate
v2 proof replay and branch final audit were also incomplete. Their handles
are missing and no process is live; there is no new routed result to accept.
Recovery is recorded in `build-toolchain-recovery/README.md`. The original
13-output proof and capture-placement proposal remain intact. Historical
manifest hashes are not being rewritten.

Recovery succeeds with exact complete routed JSON, native graph and Fmax on
the retained transport route. All old baseline objects and the chip database
match; only declared rebuilt binaries/build records differ. Original manifests
are retained unchanged. New v3 drivers require the replay control and reject
any unlisted hash difference. Both pending routes have resumed.

Both recovered implementation runs pass full routing and complete logic/BEL
checks. The 13-LUT route is **10.620 / 10.620 / 10.697 ns**, native
93.48 / 101.25 MHz. The capture variant is **10.620 / 10.620 / 10.720 ns**,
native 93.28 / 101.25 MHz. Both gates reject; neither is selected. Final
ancestry audits additionally reference the older mixed-primitive and CPU-PREG
backends. Those have been rebuilt and their separate original seed-4 routes
are replaying with exact JSON/graph/Fmax requirements; checks are not skipped.

The current native worst is DMA output FIFO write-strobe DI2, through
LUT217433 -> LUT217430 -> LUT217436 after a carry comparison. Its final
intermediate net is about 2.7 ns. The next proof cofactors late comparison
bit 53544 out of this three-node, ten-cut cone, placing the late selection at
the final LUT. It preserves all state and execution cycles; proof is running.

Both required legacy backend replays reproduce complete routed JSON, timing
graph and Fmax exactly. Final audits now require all three recovery controls;
wrong historical hashes for all four additional rebuilt artifacts are rejected.
The write-strobe cofactor passes all **1,024 cases** and actual primitive SAT,
adds five early LUTs and zero cycles, and rejects a corrupted final INIT. Its
new implementation run is in progress.

Final audits pass for the bulk-collapse route (85 original-cell moves) and
its capture variant (86), using the complete recovered ancestry. The capture
FF68661 D target is **8.287 ns** in the placement variant, while its global
DMA-strobe path still reaches 10.720 ns. A separate variant will combine that
proved placement with the newly proved strobe cofactor so both local fixes
can be assessed in the same implementation. Neither old route is selected.

The DMA strobe-only route completes at **10.557 / 10.557 / 10.557 ns**,
native **94.72 / 100.53 MHz**. Its capture combination is **10.813 ns** in
all probes, native **92.48 / 101.25 MHz**. Both final integrity audits pass
(86 and 87 original-cell moves); neither replaces the retained 10.494 ns
transport result. The recovered active-candidate stage2 summary independently
checks six candidates and 920 dependency hashes. All full timing gates reject.

The strobe-only worst FF79172 D path runs from refresh state through the
DDR read-response MUXF8. A new rewrite cofactors late net 105590 out of its
28-node, 55-cut cone. It adds 56 combinational LUTs and detaches the replaced
MUXF8 root's placement constraints while preserving all six old children's
logic. Exact canonical BDD equality and independent actual-primitive SAT pass;
a corrupted final INIT is rejected. The BDD engine also agrees with exhaustive
checks on 100 eight-LUT networks and rejects their corrupted output tables.
This is a proof result; its new full implementation is still running.

A second full route tests only FF68661's middle capture placement on the
retained transport design. This separates its effect from the intervening CPU,
critical-LUT and strobe changes. An additional read-address CE cofactor proof
is being prepared from the retained design; it is not a timing result.

The 55-cut read-response cofactor routes legally and preserves logic, but
expanded timing regresses to **14.334 ns in all probes**, native system/CPU
**69.76 / 99.35 MHz**. Its final integrity audit passes (87 original-cell
moves); it is rejected. The direct capture move on the retained transport
base reaches **10.526 ns in all probes**, native **95.00 / 101.25 MHz**,
with final integrity passing (72 moves). Neither replaces 10.494 ns.

A separate ABC experiment minimizes only the early read-response cofactors,
keeping the late signal at the final LUT and rechecking the actual candidate
with BDD and primitive SAT. The first adapter correctly stopped on Yosys
$scopeinfo metadata; v2 explicitly accepts only empty, connectionless metadata
and hashes the explicitly selected ABC executable. No failed adapter output
is used for routing. The smaller AR-ready rewrite's first two adapters also
stopped before producing a proof: an existing added replica was mistaken for
an original cell, then the verifier rejected the intentional replacement of
an already patched root. V3 retains exact base equality for every other cell
and proves the changed root against the actual composed base. Proofs are in
progress; no improvement is inferred from logic minimization alone.

The ABC cofactor variant now passes independent BDD and actual primitive SAT,
reducing 56 early LUTs to **36**. The AR-ready variant passes the same proofs
with **8 independent cuts and 4 early LUTs**. Both final INIT corruptions are
rejected by primitive SAT. Full routes have started; clocks, firmware and
execution cycles remain unchanged. The direct transport capture move's local
FF68661 D target is **8.570 ns** in its own route, while its global worst remains
10.526 ns. The stage3 recovered summary passes for eight completed candidates
and 986 hashes; 10.494 ns remains the best retained diagnostic.

The 36-LUT minimized read-response route finishes at **12.960 ns** in all
probes, native **77.16 / 100.53 MHz**. The four-LUT AR-ready route finishes at
**10.620 / 10.620 / 10.740 ns**, native **93.11 / 100.53 MHz**. Both final
integrity audits pass (87 and 72 moves), and both are rejected globally.

UART LCR CE's retained route has six LUT stages and reaches **10.440 ns**.
Cofactoring request-address bit 58573 from its seven-node, ten-cut cone adds
four early LUTs, passes BDD and actual primitive SAT, and rejects a corrupted
final INIT. Its dependency walker treats only the existing PLL's LOCKED output
as an external sequential observation, with dynamic reconfiguration absent;
this adds no PLL timing model or timing acceptance. All cone cuts remain
unconstrained in the proof. This UART variant is routing.

The write-data source is a LUT3 paired with FF68091, not an isolated LUT6.
The single-source proposal correctly stopped on its type/macro check. The
replacement proposal preserves both cells' logic and relative macro geometry,
moving LUT229059/FF68091 from X130Y132 C6LUT/CFF to X129Y86 A6LUT/AFF. All
other captures stay fixed. This separate implementation is running, and the
four-LUT UART early cofactors are also being minimized independently.

The UART four-LUT cofactor's final audit passes at **10.557 ns** in all probes
(72 moves). Its minimized one-early-LUT variant passes at **10.651 / 10.651 /
10.751 ns** (72 moves). The source LUT/FF macro placement passes at **10.620 /
10.620 / 10.720 ns** (73 moves). These routes are not selected. The stage4
recovered summary passes for ten candidates and 1,060 hashes.

The next AR enable encoding recognizes four functions of the three late
inputs, using codes [0,1,3,2]. Two early encoders have three/five-input support,
feeding one final LUT5 with all three late inputs. All 256 cases and actual
primitive SAT pass, including rejection of a corrupted final INIT. Its full
route completes at native **94.16 / 97.99 MHz**; expanded/final checks run.

Three adjacent common UART decoder pairs (218219->218218, 218308->218305,
226137->233526) also pass 80 exhaustive local cases and joint three-output
primitive SAT, with no new LUTs or cycles. The corrupted final output is
rejected. Its native route is **94.30 / 101.25 MHz**; expanded/final checks run.

Two placement controls keep the rewritten final LUT in its original BEL:
UART233526 returns from X113Y114/C6LUT to B6LUT; AR233793 returns from
X118Y75/C6LUT to X117Y74/B6LUT. Both original paired 5-LUT BELs are unused.
No logical cell changes accompany these placements, and full original legality
and routing are required again. Both new implementations are running.

Final audits pass for shared UART collapse at **10.475 / 10.475 / 10.605 ns**
(74 moves), AR encoding at **10.620 ns** in all probes (72 moves), and the two
original-final-BEL controls at **10.620 / 10.620 / 10.720 ns** (UART) and
**10.620 ns** in all probes (AR), each 71 moves. None is selected. The retained
10.494 ns result remains unchanged; the recovered stage7 summary checks 17
candidates and 1,283 hashes.

The minimized UART LCR route's actual target is **7.844 ns**, and the standalone
AR encoding's 30-register address CE group is **9.577 ns**. These local fixes
are measured in separate routes. Combining the shared UART collapses with AR
encoding passes all 256 cases and primitive SAT, including a negative INIT
control, then routes at **10.597 / 10.597 / 10.697 ns**, native **93.48 /
101.25 MHz**. Final integrity passes (75 moves); its DMA strobe path still
fails. No workload or CPU execution cycles were added.

The DFI address10 path in the shared-UART route is **10.475 ns**, launched from
bankmachine5 occupancy through LUT223080 -> LUT223079 -> LUT223078 -> LUT223072
-> MUXF8_223042 -> LUT234123. NOR3/LUT2 at 223080/223079 simplifies exactly to
one LUT4. The proof preserves the root's original LUT/FF77782 macro geometry,
keeps its original unshared 6-LUT BEL, passes 16 cases and primitive SAT, and
rejects corrupted INIT. It composes on the combined UART/AR design and is
routing. The original NOR cell is retained.

All four DMA strobe RAM inputs are driven by roots 217426, 217436, 217437 and
223961. They share the same two-LUT late-comparator prefix (217433/217430).
The next vector proof cofactors late bit 53544 from their joint six-node,
eleven-cut cone, shares early terms across all four outputs, and proves all
four outputs jointly using BDD and actual primitive SAT. It composes on the
bank5-valid candidate. Proof is running; no routed result is inferred.

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
