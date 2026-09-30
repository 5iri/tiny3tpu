# Next: common predicate across the remaining capture macros

The retained diagnostic is `build-grade2-timer-mid-zero-flag-route`:
10.358 ns in all three expanded probes, 44 failing endpoint/domain pairs,
native system/CPU 96.54/100.53 MHz, final integrity PASS. No full timing
acceptance, promotion, new RTL synthesis, or new workload simulation.

Two follow-ups did not replace it:

- `build-grade2-timer-flag-colocation-route`: 10.614 ns all probes,
  50 failing pairs, native 94.22/100.53 MHz. Twelve dead timer macro
  children removed and six existing timer cells colocated. Function and
  requested placement pass final integrity, but timing regressed.
- `build-grade2-ddr-last-capture-encoding-route`: 10.556 / 10.556 /
  10.649 ns, 63 failing pairs, native 93.91/97.32 MHz. Two additional
  capture macros (233980/233951) encoded, 12 dead children removed,
  two capture OR trees repartitioned with three late inputs. Four primitive
  SAT miters, six SAT corruption checks, three dead-cone corruption checks,
  and full final integrity pass. Worst read-valid source moves to bank2
  state FF78401 via still-unencoded macro233981. Global timing regressed.

## Read-only feasibility (not implemented or routed)

`build-grade2-timer-mid-zero-flag-route/shared-late-capture-candidates.json`
examines all 16 macro outputs feeding the ready0/read-valid9 OR trees.
Two outputs are already encoded in this parent (233945 and233977).
**All 14 remaining MUXF8 macros have the same three late functions**:
`[0,253,255]`, for late inputs `[105590,105551,105571]` in that order.
Each has five other early inputs and the checked packed ground input241167.

This allows factoring the late variables rather than encoding early
variables into two separate bits:

    common = LUT3(INIT=253, I0=105590, I1=105551, I2=105571)
    output = LUT6(early[0:5], common)

For each early assignment, the root output is respectively constant0,
`common`, or constant1. Each candidate record already contains the 64-bit
`root_lut6_table` and its ordered five early inputs. The shared predicate
is false only on late index1; use the exact truth table, not a hand-recalled
expression. The 256-assignment exploration is now backed by **14 actual-primitive
SAT proofs and 28 negative SAT checks** (wrong root truth and wrong ground
for every macro), all PASS in
`build-grade2-capture-shared-predicate-feasibility/manifest.json`.
`tools/synapse32_capture_shared_predicate_feasibility.py` reconstructs each
old macro and its common-LUT3/root-LUT6 candidate from the hashed input
netlist. This does not modify the SoC or run routing. A packed implementation
binding, exact remaining-cell checks, placement and routing are still required.

Try one local common-LUT replica for each OR group (seven roots per copy),
placed in freed macro LUT sites near its consumers. Both copies must prove
exactly the same three-input function. Root LUT6s can reuse freed sites in
their original macro slices. Existing two encoded roots and both OR trees
can initially stay as in the retained parent, isolating the new factorization.
No extra FF or execution cycle is needed. The five inherited redundant flags
(two DMA, one refresher, two timer) must remain unchanged.

Replacing the 14 roots makes their **84 old combinational children**
unobservable. `shared-late-capture-cleanup-feasibility.json` finds zero
remaining-cell output observers, zero remaining constraint references and
zero top-port observers, excluding the roots that would be replaced.
This is only feasibility: reconstruct the dead cone in the new apply helper,
validate allowed primitive types, exact root/child objects, actual ground
provenance and all remaining ports before deleting anything. Carry forward
the parent's 24 already removed cells/netnames. Do not remove state or
unrelated aliases. Freeze new scripts once hashed; retain all failed routes.

Use `build-grade2-timer-mid-zero-flag/patch.json` as the hashed parent.
Do not build from either regressed follow-up. Require four usual stages:
normal full route/pin fixup, graph normalization, all expanded timing probes
and coverage check, and final complete logical-port/placement/workload-ancestry
integrity. Corrupted LUT truth, wrong ground, observed dead outputs and
state-cell removal must fail closed. Native Fmax alone is not acceptance.

## Seed comparison

The predeclared seed set for the next promising factorization is **[4,5,6]**
for both the retained parent and the candidate. First keep the usual seed5
A/B; if promising, complete both seed4/seed6 pairs and report the distribution,
not just a winning seed. The existing retained seed5 evidence can be reused
only with exact input/proof/tool/clock/firmware provenance. No new seed4 or
seed6 run has occurred in this continuation. New helper variants must record
and cross-check the actual seed against the command; do not edit the frozen
seed5 normalizers, audits or aggregate summary's seed5 restriction.

100 MHz setup closure remains open. Generic/carry delay qualification,
clock skew/hold, reset timing and DDR IO/calibration remain separate open
physical acceptance requirements even if the expanded setup maxima pass.
