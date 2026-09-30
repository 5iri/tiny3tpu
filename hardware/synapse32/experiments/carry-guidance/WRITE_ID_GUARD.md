# Write-ID enable guard and read-response capture placement

The retained DMA-near vector candidate passes integrity at **10.507 / 10.507 /
10.595 ns**, native **94.38 MHz system / 97.99 MHz CPU**, with 150 failing
endpoint/domain pairs. The worst conservative probe ends at write-ID storage
WE. CPU-to-system DSP input reaches 10.507 ns; read-response capture reaches
10.407 ns. No full timing acceptance or promotion.

LUT228612 and LUT233727 contain seven distinct cut inputs, so they cannot be
naively merged into one LUT6. The guard factorization computes
`E = b49956 & b138940 & !(b138937 & b138938)` early, then computes
`E & (command_enable | (b49986 & !write_address_changed))` in one final LUT4.
The strict upstream dependency walk verifies that all early inputs are
independent of the two late controls and reaches only register/constant
frontiers. All 128 cut cases and actual primitive SAT pass. Corrupted early
and final LUT INITs each cause primitive SAT failure.

`build-grade2-write-id-guard/patch.json` composes with the eight-branch vector
and DMA-near placement proof. One early LUT4 is added; the old inner LUT is
retained for its other users. No state, instruction or execution-cycle changes.
The isolated full route is `build-grade2-write-id-guard-route`.

A second candidate preserves that exact logic and moves capture FF79154 from
SLICE_X118Y48/DFF to SLICE_X114Y48/BFF, beside its final F8 mux. The target slice
has no existing FFs; the original register's clock, reset, data and output
connections and parameters are unchanged. Normal placement legality and complete
routing must determine whether this location works. The isolated route is
`build-grade2-write-id-guard-rdata-near-route`. Both routing results are pending.

The new internal-node observer exposes arrivals without adding setup checks or
changing the graph. Its evaluator is an exact copy of the previous evaluator
plus the returned observation list, and domain endpoint maxima must remain
identical. This fixes the earlier inability to query combinational mux inputs;
it does not qualify any missing primitive, hold, clock, reset or DDR IO timing.

Stock-column aggregate stage 29 verifies 31 fresh routes, 28 fixed-layout
results, two reanalyses and 2,293 hashes. Parent workload evidence is composed
with combinational proofs; no fresh workload simulation or whole-RTL synthesis
is claimed for these candidates.

The DMA-near status FIFO length trace is **9.521 ns**, below its 10 ns budget.
The first write-ID guard route passes full routing, logical equality and planned
placement; native reports are 92.81 / 97.32 MHz. Expanded analysis is pending,
and the slower native result is not selected.

The guard-plus-capture placement route passes logical equality, complete routing
and every planned move. Native reports are **94.43 MHz system / 97.32 MHz CPU**.
Expanded analysis is pending. The guard-only route currently shows a 10.675 ns
zero-carry-cost worst at DMA output write strobes; it does not replace the
retained result.


Guard-only expanded probes are **10.675 / 10.675 / 10.775 ns**, limited by DMA
output write strobes; that layout is not selected. The exact write-ID storage
WE node arrives at **9.257 ns** and its exported setup check is **0.300 ns**,
so this endpoint totals **9.557 ns**, down from 10.595 ns. The internal-node
observation preserves all endpoint-domain maxima. This local fix passes 10 ns;
whole-design timing remains open.


The guard-plus-read-response placement probes are **10.517 / 10.517 /
10.590 ns**, with native 94.43 / 97.32 MHz. The capture FF79154 D now reaches
**9.861 ns**, down from 10.407 ns. Its location passes normal legality and
routing; the register's state behavior is unchanged. The full timing gate still
rejects this candidate. Final integrity is pending.

The converter selector path remains 10.590 ns: address-change reaches its mux
at 7.168 ns, then spends 2.595 ns routing to final LUT217103 near Y129. Its
capture FF is also near Y129 while the source comparison is near Y79. The
selector-register placement variant moves all 16 final LUT/FF pairs toward
Y101–106. Every register has identical clock/reset/enable controls, and target
slices originally have no FFs and no carry/mux/LUTRAM macros. Each selected
LUT6/FF pair uses vacant resources. All logic and register parameters remain
unchanged; normal legality and full routing are pending in
`build-grade2-selector-register-near-route`.


Both final integrity audits pass: 48 planned moves for guard-only and 49 for
capture placement. The combined result's 10.590 ns worst is just 0.005 ns below
the prior retained diagnostic; this tiny difference is not evidence of seed
robustness or physical closure. The meaningful local changes are write-ID WE
at 9.557 ns and read-response capture at 9.861 ns. The 16-pair selector placement
candidate is still under evaluation.

The same combined candidate confirms all three targeted paths below 10 ns:
DMA status FIFO length DI1 **9.320 ns**, write-ID WE **9.557 ns**, and
read-response capture D **9.861 ns**. The recorded `local-paths.json` binds
these selected endpoints to that candidate’s expanded graph and analysis.
This does not establish all-path closure.


The selector-register placement completes full routing, exact logic and all 65
planned moves. Native reports regress to **89.77 MHz system / 97.32 MHz CPU**;
expanded analysis is pending. It is not selected on that partial result.
Stage 30 verifies 31 fresh routes, 30 fixed-layout results, two reanalyses and
2,362 hashes; the retained diagnostic remains 10.517 / 10.517 / 10.590 ns.


The moved-selector native worst is a shared enable path, not one of the moved
registers: write-address-change -> LUT217104 -> LUT233914 -> FF75216 CE.
Its intermediate enable net takes about 2 ns to reach LUT233914. The two LUTs
have eight distinct cuts: late command-enable/read-address-change/write-address-
change and five other inputs. Enumerating the five early inputs yields only
five functions of the three late inputs (0, 170, 175, 187, 255), so a three-bit
early encoding plus one final LUT6 is possible. This is a verified truth-table
observation, not yet an implemented or routed fix; upstream independence and
full primitive proof are still required.
