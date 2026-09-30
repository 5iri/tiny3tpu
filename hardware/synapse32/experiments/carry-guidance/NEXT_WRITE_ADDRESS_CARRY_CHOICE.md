# DDR address comparison before late carry selection

The full timing gate remains false. Best retained global seed-5 interval:
10.358 ns in all probes, from the timer-mid-zero flag baseline. Stage 20
revalidation passes 53 seed-5 candidates and 3,094 hashes. The paired [4,5,6]
baseline/carry-input-inline comparison is complete; both designs fail 10 ns,
and the candidate regresses from 10.5527 to 10.5850 ns mean and from 10.686 to
10.764 ns worst. The seed metadata correction has an exact seed-5 replay control.

The broader carry-local inlining candidate replaces 394 existing identity LUTs
with their upstream functions, with joint five-input limits on paired LUTs.
Primitive SAT, two actual corrupted-LUT negatives, full routing, logical-port
comparison and final integrity pass. No state or execution cycles change.
Its probes are 10.358/10.358/10.502 ns and it has 46 failing endpoint/domain pairs.
The checked clock-domain maxima involving the CPU are now below 10 ns:
CPU→CPU 9.947 ns, CPU→system 9.584 ns, system→CPU 8.591 ns. No CPU-named state
group remains in the failing list; memory/DMA/accelerator failures remain.
This is model-based setup analysis, not hardware signoff or a new IPC simulation.

The current worst path starts at DDR write-pipe address FF70854, passes through
the low address adder's carry, then upper-address selection/comparison, then the
shared enable at LUT217104, and finally read-beat-offset FF64940. It is 10.502 ns.
The late bit is 50532 in the input JSON namespace (`main_write_offset_low[13]`);
comparison root217062 drives bit49954 (`main_write_addr_changed_parallel`).

The proposed change computes both carry cofactors early and selects between
their outputs in one LUT3. The first structural expansion is 136 LUTs, mapped
to 73. Tracing 14 early inputs back through their actual constant-producing LUTs
adds a 20-cell constant-provenance cone to the proof and reduces the mapped
candidate to 49 early LUTs. Primitive SAT checks 39 independent cut inputs with
only actual pseudo-constant drivers tied; a wrong final LUT is rejected. The
late carry is absent from every early cofactor by structural dependency analysis
across LUT, mux and carry inputs, stopping at registers/constants.

Artifacts:

- `build-grade2-write-address-late-carry-feasibility-v2/manifest.json`
- `build-grade2-write-address-carry-abc-feasibility-v2/manifest.json`
- `build-grade2-write-address-carry-choice/patch.json`
- `build-grade2-write-address-carry-choice/negative-checks.json`

The packed patch reconstructs the exact primitive miter against its actual
parent, keeps the same comparator output net, and removes only two provably
unobservable original macro children. Negative checks reject added observers,
state deletion and an incorrect constant driver. No FF, clock, firmware, ISA,
or architectural cycle changes. Placement uses free LUTs near the input-source
median and final comparison site. Full routing and final integrity pass, but timing regresses to
11.120/11.120/11.320 ns, with native system/CPU reports of 88.34/101.25 MHz.
This candidate is rejected. It adds no architectural cycles but worsens
the routed critical path.

The next candidate, `build-grade2-write-low-address-move-route`, relocates
thirteen unchanged low write-address FDRE registers near their adder
consumers. Their clock, reset, enable, initialization and logic are identical
to the joint-carry parent. The first placement fails normal legality because mux select and FF D compete
for a slice X input. The v2 candidate excludes carry/mux/RAM/SRL slices,
passes full routing and integrity at 10.633 ns in all probes. Failing pairs
drop from 46 to 31, and read-beat-offset improves to 10.068 ns. All 39
D/CE/SR endpoint checks for the thirteen moved registers are below 10 ns;
maxima are 1.569/9.492/4.154 ns respectively. No bypass of legality checks.
The next placement candidate moves the unchanged write-beat bit-2 LUT/FF
pair, now the critical launch feeding the low-adder comparison path.

The failed carry-choice trace reaches 11.320 ns through address bit 8, its
existing comparison macro, four added early LUTs, the final selector and
the shared enable. Isolating bit 13 did not make the other cofactor inputs
early; this is an observed alternate critical path, not a timing estimate.

Generic/carry delay values, skew/hold, reset recovery/removal and DDR IO remain
unqualified. Parent workload evidence is preserved compositionally; no fresh
whole-RTL synthesis or workload simulation is claimed. No promotion.
