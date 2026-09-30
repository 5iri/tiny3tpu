# Late comparison factoring across the DDR selector bus

The locked-route control's worst probe remains 11.038 ns at the native-port
converter selector. The path crosses offset arithmetic, an address-change
comparison, then two serial LUTs before the selector register.

The current candidate factors all 16 outputs of that final two-LUT structure.
Write the shared predicate as `G = E & H`, where H has four inputs including
the late read/write address-change comparisons. For each selector bit, the
original final LUT computes `Y = F(X, G)` from four other inputs X.

Two early LUTs compute:

```
base  = F(X, 0)
delta = E & (F(X, 0) ^ F(X, 1))
Y     = base ^ (delta & H)
```

The last expression fits one LUT6: base, delta and H's four original inputs.
This limits the explicit H branch to the final LUT, but X also contains a
comparison-dependent write-enable signal. The first factorization therefore
does not remove every late path. This identity
holds for every input combination, with no don't-care assumptions, new
register, ISA change or extra execution cycle.

`build-grade2-selector-patch-v4/patch.json` records the exact packed-cell edit.
All 8,192 independent cut-input cases and an independent Yosys SAT proof over
actual Xilinx LUT primitives pass. The checker rejects a corrupted cofactor
INIT. It changes 16 selector LUTs, adds 32 combinational LUTs, and leaves every
register's parameters and connections unchanged. Only placement constraints
are removed from former LUT/FF pairs; those registers keep their original BELs.

The first location plan mistakenly used pre-legalization occupancy and was
rejected before routing due to duplicate BEL assignments. The second plan
used final occupancy but hit a real LUT5/5FF output-mux conflict. The debug
legality check identified its exact failing branch; it was not bypassed.
The third plan avoids occupied 5FF output resources for the cofactor LUT pairs.
That third plan routes with correct logical behavior, but the backend moves
all 16 new delta LUTs from their planned 5LUT slots because they still used
physical O6 outputs. Its strict new-cell placement check fails; it is retained
as a rejected placement experiment. Version 4 uses O5 for those 5LUT cells.
The semantic proof passes again. The corrected route and independent integrity audit pass, with all unrelated
original cell locations fixed. Expanded probes are 11.771 / 11.771 / 12.131 ns,
so this candidate is rejected. The critical trace crosses the write-enable
LUT 217104, a new base LUT, and the final selector LUT. The best retained
worst probe remains 11.038 ns.

`build-grade2-selector-cofactors/patch.json` expands every LUT cone dependent
on either address-change comparison and computes all four Shannon cofactors.
The final LUT6 selects from those four results using the two comparisons.
The checker independently rediscovers the cones and requires every cofactor
input to be an early cut or a preceding early node. All 8,192 cut-input cases
and actual Xilinx primitive SAT pass. This version adds 96 combinational LUTs
and no state or cycles. Its fixed-placement route and integrity pass, but
expanded probes are 11.745 ns each. The worst trace now starts at read-valid
and passes through command-enable, revealing a third late control. Reserving
final LUT sites first gives 11.612 / 11.612 / 11.836 ns; it is also rejected.

`build-grade2-selector-encoded/patch.json` treats both comparisons and command
enable as late inputs. Across the six early inputs, the output has only six
distinct functions of those three late controls. Three early LUTs encode the
function, and one final LUT6 computes it. This adds 48 LUTs (16 LUT5, 16 LUT6,
16 LUT2), with all 8,192 cases and primitive SAT passing. Routing and complete
logical/placement checks pass. Expanded probes are 11.072 / 11.072 / 11.372 ns;
the worst endpoint moves to a DDR pipeline CE. The complete timing gate still
rejects. A compatible-route reuse experiment is next; no candidate is promoted.

This first run establishes the new legal placement and routed logic before
attempting compatible-route reuse. It does not claim to retain unrelated
wires. Whole-SoC 100 MHz remains unaccepted, including the existing missing
or unvalidated timing, clock, reset and DDR IO checks. Parent workload evidence
is composed with combinational proof; no fresh workload simulation or whole-RTL
synthesis is claimed for this packed-netlist experiment.

The encoded candidate's selector group is 10.374 ns (13 failing endpoint/domain
pairs), versus 11.038 ns in the retained locked control. Its whole-design count
is 262, but worst timing remains worse. A composed AW-ready collapse replaces
LUT4 228612 followed by LUT3 233791 with a single LUT6 at the final root; the
inner LUT stays for other users. All 64 independent ready cases and a combined
17-output actual primitive SAT proof pass, in addition to the selector proof.
`build-grade2-selector-ready-route` routes legally with exact logic and planned
placements. Its probes are 10.781 / 10.781 / 11.045 ns, native system/CPU
90.54 / 100.53 MHz. The new worst is write-ID-buffer occupancy, through the
still-shared 228612 predicate and an LUT8/mux structure. There are 305 failing
endpoint/domain pairs. It is not selected over 11.038 ns.

The exact lossless encoded replay passes. Cross-design import matches each
candidate physical endpoint against both the donor pre-fixup and final graph.
The first run locks 20,262 routes but fails routing a selector output; it has
no accepted timing result. Version 2 releases 449 routes touching a two-site
halo around old/new changed BELs, retaining 19,813 locked routes. It routes
legally with exact complete logic and placement, native 91.29 / 100.53 MHz.
Expanded probes are 10.781 / 10.781 / 10.954 ns: a new best worst probe,
0.084 ns below 11.038 ns. All 19,813 imported route resource sets remain
unchanged; 30,166 of 45,271 donor routed-net resource sets are unchanged in
total. The complete timing gate still rejects, and there are 337 failing
endpoint/domain pairs (more than the old locked control's 311). Worst endpoints
now belong to DMA length_active/rx_active CE, at 10.954 ns. This is a worst-path
improvement with a worse failing-endpoint count, not closure or promotion.
No routing-legality bypass or timing exception is used.

The v2 cross-design integrity audit passes, binding the exact candidate logic,
clock constraints, stock primitive model and original measured workload chain.
`critical-trace.json` starts at tx_address[1] FF77500, crosses TX-end adder54758,
the `synapse32_axi_dma.sv:53` range comparator, LUT224047, LUT224043, LUT224042,
and LUT224041/MUXF7 before FF77358 CE. This is the next worst-path target.
The counter-cone inventory is read-only: ten DDR occupancy outputs have 6–11
cut inputs, including two late controls, and several final MUXF7/MUXF8 roots.
Those roots require actual mux primitive proof and careful macro constraints
if subsequently replaced. No counter transform has been implemented or proved.

The next composed candidate, `build-grade2-selector-dma-guard/patch.json`,
factors LUT224047 -> LUT224043 -> LUT224042. The first predicate's four inputs
feed a final LUT5 directly; one new LUT6 combines the six other control inputs.
Both following original gates are proven zero when the first predicate is zero,
so the decomposition is exact for all 1,024 cut-input combinations. The existing
8,192 selector checks and a composed 17-output actual primitive SAT proof pass.
A conservative dependency walk through LUT, mux and carry cells confirms the
new early term has no dependency on either late range-comparator result. INIT
mutation checks reject both early and final guard corruption. There is one new
LUT beyond the 48 selector encoding LUTs and no state or execution-cycle change.
The fixed-placement route and independent integrity audit pass. Expanded
probes are 10.720 / 10.720 / 11.222 ns; native system/CPU are 89.11 / 97.99 MHz.
The target FF77358 CE improves from 10.954 to 10.520 ns but remains late through
the parallel bounds-check branch (224050 -> 224049 -> 224048). The global result
is rejected and does not replace the retained best.


`build-grade2-selector-dma-dual-guard/patch.json` additionally factors that
parallel branch. Its 12-input function has exactly one asserted truth-table
row. Four late comparator results feed the final LUT5; eight earlier literals
are combined in a LUT6 followed by LUT3. A conservative graph walk confirms
none of those eight early inputs depends on the selected late results. The
combined 13,312 cut cases and 18-output actual primitive SAT proof pass, with
three additional LUTs beyond the 48 selector encoders and no state or cycle
change. Its fixed-placement route and independent integrity audit pass. Expanded
probes are 10.855 / 10.855 / 10.955 ns, native system/CPU 91.28 / 101.25 MHz.
FF77358 CE improves to 9.233 ns across the probes; length_active/rx_active no
longer appear among failing groups. Total failing endpoint/domain pairs fall
from 337 to 275. The whole-design worst is now DMA status FIFO length input,
and still misses 10 ns. No promotion occurs. An exact lossless replay is running
to enable compatible donor-route reuse.


Dual-guard compatible-route reuse now completes legally with exact logic and
planned placement. `build-grade2-selector-dma-dual-guard-cross-reuse` imports
19,681 routes, after releasing 576 near changed sites. Every imported complete
wire/pip set is unchanged; 30,072 of 45,271 donor routed-net resource sets remain
unchanged in total. Expanded probes improve to **10.720 / 10.720 / 10.841 ns**,
versus the previous best 10.781 / 10.781 / 10.954 ns. FF77358 CE is **8.953 ns**
and total failing endpoint/domain pairs fall from 337 to **188**. Native system
and CPU reports are 92.24 / 97.99 MHz. The complete timing gate still rejects;
clock/hold/reset/DDR and generic/carry model qualifications are not waived.
The new worst is FF70875 CE (DDR AW-ready). The earlier separately proved
AW-ready collapse is a concrete next composition candidate; it is not yet
combined with the dual DMA guards. DDR buffer occupancy, DMA output FIFO WE,
and converter command/select paths remain above 10 ns too.

Stage 20 independently verifies the dual-guard reused route and selects its
10.841 ns worst probe as the best stock-column diagnostic. The composed next
candidate is `build-grade2-selector-dma-dual-guard-ready/patch.json`, produced
by `tools/synapse32_packed_selector_dma_dual_guard_ready.py`. It adds the already
proved AW-ready collapse to the complete dual-guard patch, with all 13,376 cut
cases and a joint 19-output actual primitive SAT proof passing. It still adds
only 51 LUTs total and no state or execution cycles. The fixed route is
`build-grade2-selector-dma-dual-guard-ready-route`; timing is pending. Its
normalizer and independent audit helpers have matching `_dma_dual_guard_ready`
names. No lossless replay or donor-route reuse of this newest composition has
yet been run.

The full ready composition now passes its independent route audit, with probes
10.781 / 10.781 / 10.877 ns. AW-ready FF70875 CE is 9.879 ns. Its new worst is
DDR occupancy update logic, investigated in [COUNTER_ENCODING.md](COUNTER_ENCODING.md).
