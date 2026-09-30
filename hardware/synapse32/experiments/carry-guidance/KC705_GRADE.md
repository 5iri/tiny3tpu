# Stock KC705 primitive timing column

The previous RAM/DSP/LUTRAM probes select the worst setup/hold/CQ value across
all six DS182 speed/voltage columns. This is retained as a conservative stress
comparison. It is not the stock KC705's specified speed/voltage column.

AMD UG810 v1.9 identifies `XC7K325T-2FFG900C` (pages 6 and 12) and nominal 1.0 V
VCCINT/VCCBRAM (pages 73 and 80). The repository's `kc705_litedram.yml` targets
`xc7k325t-ffg900-2`. The explicit stock-board assumption therefore selects DS182's
1.0 V -2/-2LE column, index 1 among the six numeric columns. This is conditional
on the stock operating configuration, not a measurement of the actual board's
part marking, voltage or temperature. No board settings are changed.

Sources:

- [AMD UG810](https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content)
- [AMD DS182](https://docs.amd.com/api/khub/documents/BhulK6GRrzUpQYw0lzrnMA/content)

`build-kc705-grade2-limits/board-evidence.json` binds the downloaded guide, PDFKit
text extraction, extractor and repository configuration. Column-selection tests
pass, including selection of both LUTRAM write-address rows from the same grade
and conservative clamping of negative hold requirements to zero. The native
include is generated from the parsed numeric limits and reconstructs the old
include exactly when only those numeric substitutions are undone.

Examples of changed limits (ns):

| Primitive check | All-column maximum | Stock -2, 1.0 V |
|---|---:|---:|
| DSP A/B to PREG setup | 5.89 | 3.90 |
| DSP PREG clock to P | 0.45 | 0.35 |
| DSP MREG clock to P | 2.31 | 1.64 |
| Boot RAM clock to output | 2.44 | 1.80 |
| LUTRAM clock to read output | 1.44 | 0.95 |

Re-evaluating existing routes changes only 22,460 CLOCK rows per probe, on the
same registered DSP/RAM/LUTRAM profiles. All ports, net arcs, combinational arcs
and symbolic carry/PCOUT probes remain exact. These are model comparisons,
not new placements or measured hardware speedups:

| Existing Wishbone-LUT route | All-column probes (ns) | Stock-column probes (ns) |
|---|---|---|
| Seed 4 | 11.746 / 11.746 / 11.746 | 11.694 / 11.694 / 11.694 |
| Seed 5 | 12.237 / 12.237 / 12.237 | 11.448 / 11.448 / 11.572 |

Both stock-column timing gates still reject. Keep these results separate from
the all-column aggregate; a different timing model is not an RTL improvement.
The new isolated native backend is `/tmp/tiny3tpu-nextpnr-grade2-guidance`.
Its disabled replay passed exact routed JSON, graph and native Fmax comparison.
Fresh seed-5 routes have completed with the stock-column costs and domain
criticality correction. All four integrity audits pass; every timing gate rejects:

| Fresh route | Beta | Weight | Expanded probes (ns) |
|---|---:|---:|---|
| Retained Wishbone-LUT netlist | 0.4 | 40 | 12.457 / 12.457 / 12.557 |
| Factored multiply sign | 0.4 | 40 | 13.043 / 13.043 / 13.743 |
| Retained netlist, denser placement | 0.6 | 40 | 16.035 / 16.035 / 16.535 |
| Retained netlist, denser placement | 0.6 | 100 | 15.175 / 15.175 / 15.465 |

None improves on the existing route reanalysis at 11.572 ns. The sign change
passes all 512 truth-table cases, but shortening one cone does not guarantee
better placement or whole-design timing. Higher density regresses substantially.
`build-kc705-grade2-limits/iterations-summary-stage1.json` keeps these fresh
routes and the two read-only reanalyses separate from the all-column aggregate.

The existing seed-5 route's 11.572 ns path is an instruction-ID to jump-address
path through a branch-selection carry chain. A new isolated candidate,
`build-ddr-cpu-preg-branch-predicate`, replaces its branch predicate with parallel
instruction-pair decodes and condition selection. All 1024 instruction/condition
combinations pass, as does independent Yosys SAT using actual Xilinx primitive
models. It adds no state or execution cycle. The original beta=0.4 placement
and timing weight 40 were used for matching seed-4/5 comparisons:

| Netlist | Seed 4 worst probe (ns) | Seed 5 worst probe (ns) |
|---|---:|---:|
| Retained Wishbone-LUT | 12.117 | 12.557 |
| Direct branch predicate | 12.163 | 11.810 |
| Branch predicate plus folded opcode guard | 12.599 | **11.169** |

The folded guard passes all 4096 arbitrary instruction/condition/guard cases
and independent primitive SAT. Seed 5 is now the best stock-column diagnostic:
11.169 ns in all three probes, native 89.53 MHz system / 96.60 MHz CPU. Its
longest path is DDR command-ready control. Seed 4 regresses; this is not a
uniform gain or a promoted default. The beta=0.3 retained-netlist seed-5 trial
reaches 12.338 ns and is not selected. All ten fresh-route integrity audits pass,
but every timing gate rejects. See `iterations-summary-stage2.json` in the
grade-limit evidence directory.

The DDR-ready LUT collapse reaches 13.442/13.442/14.042 ns. The two remaining
branch carry/decode cuts collapse to exact LUT6s and reach
11.115/11.115/11.196 ns, native 89.32 MHz system / 100.30 MHz CPU. All 2048
cases and two actual-primitive SAT proofs pass after correcting a harness-only
omission of an unobserved upper CARRY4 input driver. The failed initial harness
is retained. Seven same-edge local instruction-register copies pass actual
FDCE/FDPE reset/induction checks and reach 12.019/12.019/12.119 ns. None replaces
the best 11.169 ns diagnostic. All 13 fresh-route integrity audits pass, with
all timing gates rejecting; see `iterations-summary-stage3.json`.

A proved DSP A[29:25] tie-off on the guarded-branch candidate improves the best
stock-column diagnostic to **11.093 ns in all probes**, native 90.15 MHz system /
102.74 MHz CPU. Integrity passes, but timing remains unclosed. The new worst
trace is the ZQCS maintenance timer/control path. A same-edge zero-flag candidate
passes full control SAT and actual-counter primitive induction. Its seed-5
route reaches 11.358/11.358/11.603 ns, with a passing integrity audit and rejecting
timing gate. The targeted maintenance endpoint improves from 11.093 to 8.798 ns,
but CPU read-data arithmetic through sequencer control becomes critical. The
matching upper-input tie-off parent seed-4 route reaches
12.327/12.327/12.427 ns. Stage 6 verifies 17 fresh routes, two reanalyses and three
controls; the retained best remains 11.093 ns.

The optional stock-column checkpoint exporter passes exact routed JSON, native
guidance-graph and Fmax replay. The [standalone DSP slot option](FREE_DSP_SLOTS.md)
passes actual packer/cascade checks and disabled full replay; its enabled route
regresses to 11.740 ns. Stage 5 of the stock-column summary verifies 15 fresh
routes, two reanalyses and the three controls, retaining 11.093 ns as the best
diagnostic. No all-column stress scores are mixed into that selection.

Unchanged limitations include generic FF/LUT/mux/routing timing, combinational
TPU DSP timing, clock skew, hold analysis, reset recovery/removal, and DDR IO.
Selecting the correct registered-primitive column does not validate these.
The DS182 CLB table has been inspected, but no new generic CLB model has been
implemented or accepted.

The [sequencer choice experiment](SEQUENCER_CHOICES.md) now gives the lowest
stock-column worst probe: **11.038 ns** at seed 5, versus 11.774 ns at seed 4.
Its measured endpoint improves to 9.317 ns, but the whole timing gate still
rejects. Stage 8 verifies 24 fresh routes and two reanalyses. The separate
[pin-map controls](PIN_MAPS.md) repair constant-input label loss during
fixed-layout reimport; they do not establish a faster or timing-qualified SoC.

The [DMA control and jump-decode experiments](DMA_CONTROL_CHOICES.md) pass
combinational equivalence but do not improve the retained worst interval.
Stage 13 verifies 31 full-placement routes, three fixed-layout routes, two
reanalyses, eight controls and 1,448 hashes. The best remains 11.038 ns and
every full timing gate rejects.

The [packed logic and routing-reuse flow](PACKED_LOGIC_EDITS.md) now preserves
20,278 compatible data routes exactly, with all logical cells and BELs unchanged.
Its locked control reaches 10.781/10.781/11.038 ns, native 90.60 MHz system /
100.53 MHz CPU; the timing gate still rejects. Stage 16 verifies 31 full-placement
routes, seven fixed-layout results, two reanalyses, fifteen controls and 1,584
hashes. No default promotion or physical timing acceptance is claimed.

Stage 17 adds four proved selector packed-netlist routes, detailed in
[SELECTOR_BUS.md](SELECTOR_BUS.md). Worst probes are 12.131, 11.745, 11.836,
and 11.372 ns. The best retained 11.038 ns diagnostic is unchanged. The
aggregate verifies 31 fresh routes, 11 fixed-layout results, two reanalyses,
and 1,712 hashes. No timing model column, clock constraint, firmware byte,
or execution cycle is changed by these experiments.

Stage 18 adds the composed selector/AW-ready route and the compatible-route
reuse. The aggregate verifies 31 fresh routes, 13 fixed-layout results, two
reanalyses and 1,779 hashes. New best stock-column probes are **10.781 / 10.781 /
10.954 ns**, from `build-grade2-selector-encoded-cross-reuse-v2`. Native reports
are 91.29 MHz system / 100.53 MHz CPU. Every imported one of 19,813 routes keeps
its complete wire/pip set. Worst delay improves by 0.084 ns, but failing
endpoint/domain pairs increase from 311 to 337. The full timing gate still
rejects; all-column stress results, clock constraints and model limitations
remain separate and unchanged. No default promotion occurs.

Stages 19–20 add the DMA range-guard factorizations and compatible-route reuse.
Stage 20 verifies 31 fresh routes, 16 fixed-layout results, two reanalyses and
1,877 hashes. New best probes are **10.720 / 10.720 / 10.841 ns**, native system /
CPU 92.24 / 97.99 MHz, from `build-grade2-selector-dma-dual-guard-cross-reuse`.
FF77358 CE is 8.953 ns; failing endpoint/domain pairs fall from 337 to 188.
All 19,681 imported wire/pip resource sets remain unchanged. Proof composition
preserves state and execution cycles. Full physical timing remains unaccepted,
with the same model, clock, hold, reset and DDR limitations. No promotion occurs.


Stock-column aggregate stage 22 verifies 31 fresh routes, 21 fixed-layout
results, two reanalyses and 2,042 hashes. The retained diagnostic is the linear
counter encoding with compatible-route reuse: 10.781 ns in all three probes.
The [reset cofactor experiment](RESET_CHOICE.md) improves its local
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

Stage 32 verifies 31 fresh routes, 33 fixed-layout results, 2 reanalyses and
2,461 hashes. Main-CE and selector-feedback fixes shorten their local paths
but do not improve the retained 10.590 ns global diagnostic. The full timing
gate remains false. Details: MAIN_CE.md.

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
