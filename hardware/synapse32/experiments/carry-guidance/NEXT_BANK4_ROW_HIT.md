# Bank4 row-hit timing iteration

Retained baseline: `build-grade2-timer-mid-zero-flag-route`, 10.358 ns in all
three stock-column probes, 44 failing endpoint/domain pairs. No timing closure.

The next five capture/placement routes all pass final integrity but regress:

| Candidate | Expanded interval, all probes |
| --- | ---: |
| Shared capture predicate | 10.938 ns |
| All capture early encoding | 10.382 ns |
| Whole OR factorization | 11.094 ns |
| OR/timer colocation | 10.839 ns |
| CPU instruction-ID pair placement | 10.691 ns |

Bank4's old row-hit cone has 27 combinational cells and 29 FDRE source
registers. The exact predicate is row-open AND equality of the two 14-bit
row addresses. All original registers have INIT=0 and the same system clock.
The address groups have distinct enables; row-open has a separate reset.

`build-grade2-bank4-row-hit-flag-v2/patch.json` adds 19 LUTs and one INIT=0
FDRE flag, updated on the same edge as its source registers. All original
state is unchanged. The original comparator remains with an unused output.
The new flag drives the original predicate net. Its packed primitive miter
preserves actual shared source wires and passes finite proof plus induction.
Four actual primitive corruptions are rejected. Five more feasibility
negatives include missing enable holds and reset semantics. Observer checks
terminate at synchronous inputs on the same clock.

`build-grade2-bank4-row-hit-collapse/patch.json` instead uses five parallel
LUTs, each comparing up to three row-bit pairs, and one final AND LUT. It adds
no state. Primitive SAT proves all 29 input combinations symbolically, and
both corrupted comparison/reduction variants are rejected. Unused original
macro children remain with their parent constraints cleared.

Both candidates completed full routing and final integrity. The first flag
misses at 10.980 ns, exactly at its new D input. The purely combinational
version reaches 10.639/10.639/10.714 ns and is also rejected.

The revised `bank4-row-hit-late-enable-flag` exploits the exact wiring
row_D=pipe_Q. It computes address equalities early and isolates the late
enable in a final LUT5. Fifteen LUTs and one redundant INIT=0 flag preserve
the original result on the same edge. Its actual primitive induction includes
flag feedback and all shared wires; four corruptions are rejected. Flag D
now reaches 8.930 ns. Global timing is still 10.633 ns, limited by bank2 state
through read-valid9. Removing the complete unobserved 27-cell old comparator
passes three observer/state-deletion negative controls and full routing, but
leaves the same 10.633 ns interval.

The independent CPU branch-decode placement moves seven unchanged LUTs and
closes the worst jump-address group to 9.104 ns. Global timing is 10.411 ns
with 43 failing endpoint/domain pairs, versus 44 in the retained baseline.
The next CPU candidate inlines a LUT4 generate predicate into the carry's
existing A5LUT buffer. The A5/A6 functions together use exactly five inputs;
actual SAT, a corrupted-predicate negative, routing legality, full logical
port equality and expanded audits pass. The worst signed/unsigned comparison
input group reaches 9.247 ns. Its global interval ties 10.358 ns, but 51 pairs
still fail. No register or architectural latency changes.

The paired-seed plan `build-grade2-branch-carry-seed-plan.json` declares
baseline and carry-inline candidate at seeds 4, 5 and 6 before any new 4/6
runs. Seed 5 is already complete. Four additional routes and full audits are
running serially through `tools/synapse32_branch_paired_seed_run.py`; progress
is in `build-grade2-branch-paired-seed-status.json`. The comparison summary
requires all six distinct design/seed cases and checks the seed stored in each
routed JSON. No distribution or seed robustness is claimed while incomplete.

No fresh whole-RTL synthesis or workload simulation is claimed. State-machine
scheduling and instruction timing are unchanged by the proved transformations.
Generic/carry models, skew/hold, reset recovery/removal, and DDR IO/calibration
remain unqualified. No seed-robust gain, hardware signoff, or promotion.


## Seed metadata correction and broader carry experiment

The initial seed-4 route was rejected because its output still recorded seed 5.
Source inspection shows command handling initializes the live RNG before JSON
import, whose settings overwrite the recorded seed fields. The v2 route helper
removes only `seed` and `seed.arg` from imported settings. The corrected seed-5
control reproduced the full routed JSON, timing graph, and native clocks exactly:
`build-grade2-seed-metadata-replay-integrity.json` passes. Old failed artifacts
remain intact. The unchanged seed/design set restarts under
`build-grade2-branch-carry-seed-plan-v2.json`, with progress in
`build-grade2-branch-paired-seed-status-v2.json`.

Both corrected seed-4 audits pass: baseline 10.614 ns in all probes; candidate
10.614/10.614/10.764 ns. The candidate regresses on the worst probe. Seed 6 is
still pending, so no full distribution is claimed yet.

A read-only inventory found 402 carry-local identity buffers whose one-upstream
LUT could fit alongside the unchanged paired LUT. Joint selection rejects eight
pin conflicts and retains 394 replacements. A combined actual primitive miter
proves all 394 old/new functions over 897 independent cut inputs; two corrupted
actual LUTs are rejected. The packed patch reconstructs and binds that same
miter against its actual parent netlist, checks every final paired five-input
limit, and preserves all upstream cells, carry placement and state. The patch is
`build-grade2-joint-carry-buffer-inline/patch.json`; its separate seed-5 route
is in progress. No timing gain is claimed for this broader edit yet.
