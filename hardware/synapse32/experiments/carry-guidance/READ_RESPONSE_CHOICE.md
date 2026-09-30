# Read-response selector cofactor

The retained 10.781 ns stock-column diagnostic ends at DDR read-response-valid
FF79154 D. Its trace traverses selector macros 228224, 233967 and 233963.
Cofactoring the complete suffix after 228224 would cover 28 nodes and 55 cuts.
The bounded experiment instead replaces only macro 233967, whose late-dependent
cone has three nodes and ten cut inputs.

`tools/synapse32_packed_read_response_choice.py` composes with the linear counter
patch. Six added LUTs compute the two cases of late bit 105590, followed by a
final selector LUT. The dependency walk includes LUT/mux/carry logic and rejects
unsupported late-dependent carry logic. All 1,024 cut combinations and actual
Xilinx LUT/MUXF7/MUXF8 primitive SAT pass. The verifier also checks exact original
cells, inherited patch contents, early-input independence and detached macro
child attributes. No state or CPU cycle changes.

`build-grade2-read-response-choice-route` is the full fixed-layout route under
evaluation. Legality, complete logical-port equality, exact requested placement
and expanded timing must pass their respective checks before comparison. A
local Boolean proof alone is not a timing result or a new workload measurement.
Physical clock/reset/DDR IO and generic/carry-model qualification remain open.

Negative checks reject early/final INIT corruption, injection of the late signal
into an early LUT, and incorrect retained macro-child attributes.


The first route reaches **11.384 ns in all three probes**, native 87.84 MHz
system / 97.99 MHz CPU. The full gate rejects it. Its worst path remains
FF79154 D, now through three serial early LUTs followed by the final selector.
This candidate is not selected.

The collapsed variant combines the last two early mux LUTs in each cofactor.
It uses four added LUTs instead of six and removes one serial stage. All 1,024
cut cases and actual primitive SAT pass again. Its isolated full route is
`build-grade2-read-response-choice-collapsed-route`, under evaluation. The
original evidence-hashed mapper and route remain unchanged.

The collapsed route passes original legality, exact planned placement and
complete logical-port equality. Native reports are 89.77 MHz system /
100.53 MHz CPU. Expanded analysis remains pending; native CPU timing alone
is not full-SoC timing acceptance.


Expanded collapsed probes finish at **11.034 / 11.034 / 11.139 ns**. This
improves the six-LUT result but remains worse than the retained 10.781 ns and is
not selected. FF79154 D is 11.034 ns. Its path reaches LUT228242 output at
5.673 ns, the first early LUT at 7.328 ns, the collapsed early LUT at 8.068 ns,
the final selector at 8.808 ns and the endpoint including setup at 11.034 ns.
Thus an allegedly earlier cut is also late; a next two-control decomposition
should consider both original bit 105590 and the LUT228242 output, verified as logical bit **105612**. The conservative carry probe
exposes another 11.139 ns endpoint. Full timing acceptance remains false.

The collapsed route independent integrity audit passes; it remains rejected on
timing. No fresh workload simulation or whole-RTL synthesis was run.


The two-control encoded candidate treats bits **105590 and 105612** as late.
Across eight other cut inputs it selects exactly four functions of those bits:
0, 12, 13, 15. Encoding those as 0, 1, 3, 2 gives two six-input early functions
and a final LUT4. It adds only two LUTs. All 1,024 cut cases and actual primitive
SAT pass. A read-only LUT/mux/carry dependency walk finds no dependency of any
of the eight early cuts on either late bit. The verifier rejects direct use of
either late bit in an early encoder. No register or execution-cycle changes.

`build-grade2-read-response-encoded-route` is routing; no timing result is yet
claimed. Prior mapper/proof files are frozen. Aggregate stage 25 verifies 31
fresh routes, 24 fixed-layout results, two reanalyses and 2,133 hashes, including
both rejected cofactor layouts. The best diagnostic remains 10.781 ns.


The single encoded route passes integrity, with **10.901 / 10.901 / 11.001 ns**,
native 90.90 MHz system / 97.99 MHz CPU. The global worst is DMA status FIFO
length DI1. FF79154 D remains 10.781 ns, now through untouched macro **233965**
instead of the edited 233967. Five negative checks pass, and the persisted
upstream dependency audit reaches only register/constant frontiers. The exact
lossless replay passes; compatible-route reuse is running.

There are eight matching read-response branches: 233964, 233965, 233967, 233968,
233969, 233970, 233972 and 233973. Each branch admits the same two-LUT6 encoder
and final LUT4, with a branch-specific second late control. The vector candidate
will compose all eight component proofs and additionally prove their eight
outputs jointly, before a full fixed-layout route. No timing result is claimed
for the vector candidate yet.


The vector proof is complete: **8,192 exhaustive branch cases** and an
**eight-output primitive SAT proof across 52 shared cut inputs** pass. Sixteen
encoder LUTs are added beyond the counter base. The compositor checks exact
component unions, unique added signals, no cross-component output/cut
interference, and common base proof identity. It assigns new BELs jointly to
avoid placement collisions between independently generated components.
All eight upstream early-cut dependency checks pass, terminating only at
registers or constants. `build-grade2-read-response-vector-route` is running.

Aggregate stage 26 verifies 31 fresh routes, 25 fixed-layout results, two
reanalyses and 2,174 hashes. It includes the rejected single-branch encoded
route, its negative/dependency checks and exact lossless replay. The retained
best remains 10.781 ns; no full timing acceptance or promotion.


The single-branch compatible-route result reaches **10.781 ns in all probes**,
native **92.76 MHz system / 101.25 MHz CPU**. All **19,063 imported route
resource sets** are unchanged. Expanded CPU-to-system timing still exceeds
10 ns, and the full timing gate rejects the result. The vector verifier also
rejects a missing branch and a corrupted merged root INIT.


The vector route passes exact logic and planned placement. Native reports are
91.81 MHz system / 97.99 MHz CPU; expanded probes are **10.792 / 10.792 /
10.892 ns**, limited by DMA status FIFO length DI1. The targeted DDR
read-response-valid FF79154 D improves to **10.407 ns**, still above 10 ns.

A placement-only variant moves DMA carry macro 59318 and its eight children
from SLICE_X108Y135 to SLICE_X110Y87, plus output LUT223893 to
SLICE_X109Y87/C6LUT. Source register FF75270 is at SLICE_X107Y82. The original
route takes a long trip to Y135 and back to status logic near Y82. All logic,
parameters and macro constraints remain unchanged; normal placer legality and
exact requested moves must pass. `build-grade2-read-response-vector-dma-near-route`
is running. No timing result is claimed for this placement variant yet.


The DMA placement variant completes routing and passes exact logic and all 47
planned moves. Native reports improve to **94.38 MHz system / 97.99 MHz CPU**.
Expanded analysis is pending. The native worst now ends at write-ID storage WE:
write-address-change -> LUT228612 -> LUT233727 -> memory.storage_15 WE.
Those two LUT4s have seven distinct cut inputs, so a naive LUT6 collapse is not
valid. The useful next factorization keeps address-change and command-enable
late, computes a four-input early guard, and combines it with the other early
control in a final LUT4. This is a proposal requiring proof and routing, not an
implemented or measured improvement.

The existing endpoint trace helper rejects a combinational-only 233963 selector
query because it returns no tracked register inputs. No timing result was
produced by that query; the valid FF79154 endpoint trace remains authoritative.
