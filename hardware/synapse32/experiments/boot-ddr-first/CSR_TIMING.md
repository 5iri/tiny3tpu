# Continued full-design timing work

The retained best expanded diagnostic is still UART-reset guided seed 8:
11.936/11.936/12.105 ns. Physical 100 MHz is not closed. This continuation
starts from the proved boot/DMA/DDR/branch composition and attacks additional
failing endpoints without changing instruction or workload cycle counts.

## Exact RTL changes

`csr_predecode.py` captures 19 full PHY CSR address predicates on the **existing
CSR address capture edge**. The address register has INIT=0, an enabled writer
and no reset; the predicates preserve exactly that behavior, including holds.
Temporal induction covers arbitrary 14-bit addresses and capture enable.
Exactly 38 read/write decode occurrences use the predicates. No CSR access
edge, reset priority or read/write strobe changes.

`read_credit.py` changes the five-bit DDR read-credit counter to parallel bit
updates and caches its full predicate. Induction proves the count and full
flag for arbitrary enqueue/dequeue/reset, including simultaneous events and
modular overflow. Read issue timing and payloads are unchanged.

`multiply_blocks.py` combines signed multiply partial products with two
carry-save levels and an eight-bit block carry-select sum. An exact SAT proof
covers arbitrary partial words and both result selections. Partial-product
registers, resets and the output register edge are unchanged. No instruction
or pipeline stage is added. The resulting four registered DSPs have pure
multiply profiles without cascade consumers.

Frozen drivers: `run_csr.py`, `run_read_credit.py`, `run_mul_blocks.py`.
Each provides `prepare`, `prove`, `smoke`, `gemm`, `synth` stages and a required
fresh `--out` directory. Proofs precede simulation and synthesis. Yosys uses
the same source snapshots, primitive libraries and Slang plugin as before.

All three candidates pass fresh smoke and 45-shape CPU/DMA/TPU runs with every
PROFILE, METRICS and DMA field exact. Full diagnostic: **1,659,843 instructions,
2,084,686 CPU edges, 0.7962076783 IPC, 11,544,608 system cycles**. Firmware and
original XDC bytes remain identical. These are variable-latency-memory
workloads; the generated DDR-controller changes have the separate proofs above.

## Completed carry-guided seed-4 comparisons

Each row is a real synthesis and legal KC705 route, under the original 100 MHz
constraints. Columns use the same symbolic `(PCOUT, carry arc)` probes:
`(0,0)`, `(1,0)`, `(0,0.1)` ns. These are model intervals, not physical bounds.

| Composition | Expanded probes (ns) | Build/model stem |
|---|---|---|
| Previous branch composition | 12.376 / 12.376 / 12.376 | `build-ddr-boot-first-branch4-timing` |
| Above + CSR predecode | 13.343 / 13.343 / 13.343 | `build-ddr-csr-predecode` |
| Above + read credit | 13.349 / 13.349 / 13.649 | `build-ddr-csr-read-credit` |
| Above + blocked multiplier | 13.529 / 13.529 / 13.729 | `build-ddr-csr-mul-blocks` |

For the last three rows append `-route/seed-4`, `-timing`, or `-coverage` for
route, expanded model, and timing-check artifacts. The failed clock target is
retained in each report; no candidate replaces the overall 12.105 ns baseline.

The CSR-only layout moves the worst interval to a DSP input. Read credit's
layout has a bus-data path longest. The blocked-multiplier layout has a final
multiply result path longest. Placement changes elsewhere can overwhelm a
local RTL improvement. `tools/synapse32_timing_hotspots.py` recomputes all
failing system/CPU setup endpoint/domain pairs and groups them by state signal
to avoid optimizing only one reported worst path. These counts are not counts
of all combinational paths, and do not cover hold or DDR IO.

`tools/synapse32_csr_iteration_audit.py` binds each candidate's proof records,
exact functional results, synthesis inputs, route, expanded model and rejected
timing check. An integrity pass explicitly retains timing acceptance as false.
The resulting records are `iteration-integrity.json` in each build directory.

## Primitive timing during optimization

The original backend ignores the boot RAMs and registered DSP timing. The
independent expanded analyzer detects their failing paths after routing; it
cannot make the placer optimize them. An isolated backend now supplies the
same narrow DS182 boot-RAM and pure MREG-multiply profiles during optimization.
The existing carry guidance remains explicitly symbolic.

Sources: `../carry-guidance/primitive_timing.inc`,
`tools/synapse32_build_primitive_guidance.py`,
`tools/synapse32_primitive_guided_seed_sweep.py`, and
`tools/synapse32_primitive_guidance_normalize.py`.

The successful isolated build is
`/tmp/tiny3tpu-nextpnr-primitive-guidance-v2`. The original compile attempt
used an unavailable Property accessor and failed; its artifacts are retained
under `/tmp/tiny3tpu-nextpnr-primitive-guidance` and are not used.

Both optional features are disabled by default. Disabled replay in
`build-primitive-guidance-disabled-replay` reproduces the original routed JSON,
timing graph and native clocks byte for byte. Original binaries, sources and
link inputs retain their hashes. Seven normalization tests check exact timing
rows and reject missing checks, changed setup/hold, ignored capture ports and
unsupported hybrid DSP bypass paths.

An enabled route is usable only if every added RAM/DSP classification and
clock check matches the independent model. The raw native graph remains
available. The normalized comparison graph removes only the added models and
symbolic carry arcs; routed connections and delays remain exact, then the
established expanded analyzer reapplies its models. Pure MREG outputs use
native REGISTER_OUTPUT rather than the offline engine's clock-origin-capable
COMB_OUTPUT; absence of all bypass arcs is mandatory for this equivalence.

This backend improvement does **not** validate generic cell delays, carry
delays, clock skew/hold, reset recovery/removal, DDR IO, or hardware operation.
The initial primitive backend still excludes native LUTRAM write-clock origins.
The subsequent mixed-output backend described below adds them while retaining
asynchronous read-address paths. No physical timing acceptance is
inferred from native MHz.


## Read DMA, beat counts and CSR readback

`read_address_advance.py` applies the proved short-profile carry-select update
to DMA reads as well as writes. `local_peripheral.py` removes the irrelevant
external-ready dependency from local DMA/TPU acceptance. `burst_counts.py`
computes the short-profile beat counts directly, including the original
zero-length underflow. All DMA state bits and module ports remain equivalence
boundaries; no descriptor, backpressure or initialization assumptions are used.

`atomic_divider.py` composes the existing proved atomic result selection and
divider sign alternatives. It preserves all atomic instructions, controls and
reservation state, divider completion/cancel edges, and instruction latency.

`csr_readback.py` captures 51 additional address predicates on the existing
address edge and uses all 70 predicates in the three existing registered read
banks. Temporal induction checks arbitrary read values and full addresses,
hold and INIT. No CSR access edge is added. In its primitive-guided seed-4
layout, the CSR readback group is 8.835 ns (the earlier dual-DMA layout was
12.072 ns), but other DDR paths make the whole-design result worse.

All these completed RTL candidates pass smoke and all 45 GEMM shapes with
identical PROFILE/METRICS/DMA fields and binary/hex/XDC bytes. Full diagnostic
IPC remains 0.7962076783 and system cycles remain 11,544,608. This is CPU/DMA/TPU
simulation with variable-latency memory; generated DDR controller changes have
separate proofs and are not validated by a DDR PHY simulation.

| Candidate / backend / seed | Expanded probes (ns) |
| --- | --- |
| Blocked multiplier / RAM+DSP guidance / 4 | 13.525 / 13.525 / 14.625 |
| Dual DMA advance / RAM+DSP guidance / 4 | 12.072 / 12.072 / 12.155 |
| Local DMA/TPU acceptance / RAM+DSP guidance / 4 | 12.875 / 12.875 / 13.105 |
| Atomic + divider / RAM+DSP guidance / 4 | 13.590 / 13.590 / 13.790 |
| Direct burst counts / RAM+DSP guidance / 4 | 14.238 / 14.238 / 14.438 |
| CSR readback / RAM+DSP guidance / 4 | 13.013 / 13.013 / 13.013 |
| Dual DMA / mixed RAM guidance / 4 | 13.131 / 13.131 / 13.331 |
| CSR readback / mixed RAM guidance / 4 | 14.382 / 14.382 / 14.582 |
| Dual DMA / mixed RAM, timing weight 40 / 4 | 12.118 / 12.118 / 12.312 |
| Dual DMA / mixed RAM, timing weight 40 / 8 | 11.575 / 11.575 / 12.275 |
| Dual DMA / mixed RAM, timing weight 100 / 4 | 13.396 / 13.396 / 13.596 |

The three probes remain `(PCOUT, carry arc)` = `(0,0)`, `(1,0)`, `(0,0.1)` ns.
They are symbolic optimization diagnostics, not validated physical bounds.
None of these routes replaces the retained 12.105 ns baseline.

## Mixed LUTRAM timing in native placement and routing

The isolated `/tmp/tiny3tpu-nextpnr-mixed-primitive-guidance` backend adds write
setup/hold and clock-to-read origins for the current RAMD32 profile. Native
COMB_OUTPUT nodes now retain both their combinational read fanin and clock
origins. Clock origins are seeded before the topological walk, but mixed
outputs are not queued until read fanin is ready. Backtracing and printed
paths recognize clock-origin dominance. Unsupported RAM/DSP profiles abort.
The original source, objects and binaries remain unchanged.

Sources are `../carry-guidance/mixed_primitive_timing.inc`,
`../carry-guidance/mixed_output_patch.py`, and the
`tools/synapse32_{build_mixed_primitive_guidance,mixed_primitive_guidance_replay,
mixed_primitive_guidance_normalize,mixed_primitive_guided_seed_sweep}.py` tools.
The disabled replay reproduces routed JSON, graph and native clocks exactly.
Enabled full-SoC routes match the independent RAM/DSP/LUTRAM models: 16 boot
RAMs, 4 registered DSPs and 2,603 observable LUTRAM cells, with 20,824 added
LUTRAM clock-check rows. Raw graphs are retained; normalization preserves
all net delays and read arcs before independently reapplying the models.

Six normalization tests reject missing clock origins, changed write setup or
hold, a register-only output classification, and unknown RAM profiles.
`build-mixed-lutram-microtests/audit-v2/results.json` additionally checks three
real routed microdesigns against the independent graph walker. The long-read
case needs the asynchronous read arcs (7.900 ns versus 4.849 ns if removed);
the fixed-read-address case needs the write-clock origin (2.064 ns versus
1.279 ns if removed). These tests exercise the timing algorithm, not physical
FPGA delay validation. The first RAM32X1D fixture is retained as an expected
unsupported-profile rejection; a RAM32M fixture exercises the current profile.

`tools/synapse32_mixed_weighted_seed_sweep.py` changes only the placer's timing
weight in a separate JSON input. It asserts the logical netlist is exact after
removing that single setting, retains source/input hashes, and keeps the
original 100 MHz XDC and command target. It introduces no timing exceptions.

Two expanded/check report writes ran out of disk space. Their partial outputs
remain rejected in `build-ddr-csr-readback-mixed-timing` and
`build-ddr-dual-dma-mixed-coverage`; fresh `-retry` directories contain the
completed reruns. Lossless APFS compression records hash-check all compressed
artifacts; no previous results were deleted.

Physical 100 MHz remains unclosed. Carry costs, generic cell/routing delay,
clock skew/hold, reset recovery/removal and DDR IO signoff remain unvalidated.
Native model coverage improvements do not relax the acceptance gate.


## Single carry-save level and signed DDR offsets

`multiply_single_csa.py` joins the disjoint high-high and low-low upper partials
into `{p11[31:0],p00[31:16]}` before reducing the three operands. This removes
one carry-save level while preserving the final block adder and all registers.
SAT proves low/high results for arbitrary signed partial words and selection.
The paired count/readback parent and single-CSA synthesis use 6,665 and 6,363
LUT6s respectively, with identical FF, DSP and RAM counts. Both workloads remain
exact. Their seed-8, weight-40 native system reports are 72.10 and 79.84 MHz;
Their expanded probes are 13.670/13.670/13.870 ns and
12.125/12.125/12.525 ns. This is a paired improvement, but remains worse
than the retained baseline. Single-CSA seed 4 is also retained as a regression.

`ddr_offsets.py` replaces the two generated 30-bit base-plus-signed-13-bit-offset
sums with a low-part sum and precomputed upper increment/decrement alternatives.
The proof covers every base and signed offset, including negative wrap and
address overflow, without traffic/alignment assumptions. Registers, handshakes
and latency are unchanged. `build-ddr-signed-offsets` passes proofs, both exact
workloads and synthesis; its seed-8 expanded probes are 12.922/12.922/13.622 ns. CPU native
101.11 MHz does not establish whole-system timing; the longest path ends
at a LUTRAM write-enable in the DDR write-ID queue.

Frozen drivers `run_count_readback.py`, `run_single_csa.py` and
`run_ddr_offsets.py` accept `prepare/prove/smoke/gemm/synth --out FRESH_BUILD`.
The first is an ablation that excludes the local DMA/TPU acceptance rewrite.
`tools/synapse32_ddr_offset_iteration_audit.py` requires the additional proof
when signed-offset logic is present. The complete iteration inventory is
produced by `tools/synapse32_csr_iterations_summary.py`; pending work is listed
explicitly and never counted as an accepted timing result.


`dma_parallel_advance.py` and `read_dma_parallel_advance.py` calculate the
final-transfer and burst-limited address alternatives before the final selection.
The remaining count is zero for the final transfer; the limited subtraction is
computed in parallel. Full current-profile DMA state/port equivalence and exact
arithmetic checks pass without traffic, alignment or zero-length assumptions.
`build-ddr-parallel-dma` passes both exact workloads and synthesis.

`multiply_prefix.py` tests a balanced, kept group-carry network, direct block
propagate bits and independently computed sum-with-carry alternatives. Its full
arithmetic proof and workload checks pass. It is isolated from the DMA/offset
combination so its placement effect can be assessed separately.

A traced signed-offset write path shows the optimizer sharing arithmetic across
the late low-carry selection, recreating a dependent upper carry chain. The
`ddr_offsets_keep.py` experiment adds keep attributes to the two upper-address
alternatives. Its synthesized structure must be inspected before attributing
any timing improvement to preserved parallelism.

`tools/synapse32_trace_timing_cell.py` adds direct physical-cell tracing, which
is needed for RAM write-enable endpoints without a flip-flop Q state name.
The original state-net tracer deliberately rejects such a selection; it was not
used to claim a missing RAM path was absent.


Follow-up structural check: `structure-audit.json` used disconnected Yosys
net-name aliases as address endpoints, so its zero-chain result does not establish
independence. `structure-audit-v2.json` follows live upper-adder outputs by source
location and finds five carry cells per direction reachable from the late carry
in both the parent and kept-alternative candidate. The keep-only structural test
fails; no improvement is attributed to it. `ddr_offsets_prefix.py` instead spells
out upper increment/decrement bits with prefix reductions, without adding state.

The completed 20-route inventory is hash-checked in
`build-ddr-csr-predecode/iterations-summary-stage3.json` (2,004 hashes). All routes
remain rejected for whole-SoC closure; the retained 12.105 ns diagnostic is unchanged.
The parallel-DMA and balanced-multiplier routes reached 13.765 ns and 13.860 ns
respectively in the largest symbolic probe and were not selected. The proposed
product-sign shortcut timed out in its bounded proof and was not implemented.


The keep-only route completed at 12.281 / 12.281 / 12.581 ns and remains
rejected. The explicit prefix candidate (`build-ddr-prefix-offsets`) passes all
formal checks, exact smoke/GEMM counters, and synthesis. Its version-three
structure audit hashes both RTL snapshots, follows live endpoints, and confirms
five late-carry-dependent upper carry cells per direction in the parent versus
zero in the prefix candidate. Placement/routing is being measured at seeds 8
and 4 with weight 40; structural improvement alone is not timing closure.


Prefix-offset routes completed: seed 8 is 12.894 ns in all three probes,
seed 4 is 12.500 ns in all three. Native system/CPU figures are 77.56/95.58 MHz
and 80.00/94.52 MHz. Both integrity audits pass while timing acceptance fails.
The write-address state group remains 11.894/11.484 ns, with long paths through
native-port address selection/comparison and ready generation. The new
`ddr_compare.py` experiment compares read and write address alternatives before
arbitration selection. Its combinational SAT proof preserves both-selection
read priority and neither-selection default zero, with no grant assumptions.
The complete proof suite, exact smoke/GEMM counters, and synthesis pass.
Fresh weight-40 routes at seeds 4 and 8 are in progress.


The parallel-comparison routes completed at 13.097/13.097/13.297 ns (seed 4)
and 13.085/13.085/13.285 ns (seed 8). Both fail timing acceptance; integrity and
all throughput/correctness comparisons pass. The intended write-address state
group improves from 11.484 to 10.471 ns at seed 4 and from 11.894 to 10.793 ns
at seed 8, but whole-design regressions prevent selection. The worst endpoints
are multiply_result[27] and UART rx_fifo_count[4], respectively. Their traces are
retained in `build-ddr-parallel-compare`. The 25-route aggregate checks 2,435 hashes
and keeps the original 12.105 ns diagnostic. No 100 MHz closure is claimed.

`uart_prefix.py` is the next isolated experiment. It replaces only the RX/TX
occupancy increment/decrement blocks with parallel bit predicates; it retains
all UART reset, interrupt, data-storage and protocol logic. The complete formal suite passes in `build-ddr-uart-prefix`, including all
32 occupancy values and all push/pop/clear/reset combinations. The sequential
workload/synthesis/route run has started; no timing improvement is claimed.


UART-prefix formal, smoke, GEMM and synthesis stages now pass, with every
PROFILE/METRICS/DMA field unchanged. Seed 4 routing is in progress. The UART
trace before this rewrite starts at system reset and passes through control
logic and the occupancy adder; this change targets the adder portion, not the
entire reset path.

A possible next multiplier experiment is register-boundary balancing: capture
the carry-save sum/carry and low 16 bits at the existing partial-product edge,
then keep the final result edge unchanged. This is only under consideration;
no RTL or timing claim is made for it. It needs an inductive state-relation
proof from reset, exact workload/cadence validation, and inspection of DSP
register inference. In particular, an AREG/BREG-only DSP profile is outside the
current narrow native model; it must not be silently routed as a modeled MREG
profile. Fully combinational DSPs would also require explicit profile/arc
coverage checks, and the current independent registered-DSP helper asserts
that at least one registered profile exists.


The UART-prefix seed 4 route completed at native 81.01 MHz system / 96.11 MHz
CPU. Expanded analysis is pending; this is not closure. A separate unpromoted
`build-ddr-multiply-retime` candidate now implements register-boundary balancing.
Its full proof suite has started. Before any timing comparison, its new
retiming proof must be composed with the retained single-CSA arithmetic proof,
and its synthesized DSP register profiles must be checked against model support.


The UART-prefix route expands to **12.268/12.268/12.368 ns**. Integrity passes,
closure fails, and the retained best diagnostic remains 12.105 ns. Its DDR ID
FIFO, write queue and buffer groups are 9.390, 9.840 and 9.054 ns, while DMA
address/remaining groups are still 10.845/10.569 ns.

`build-ddr-multiply-retime` passes full proofs, the composed arithmetic/temporal
induction, exact workloads and synthesis. It infers four DSPs with MREG=PREG=0
and AREG/BREG combinations 11,10,01,00. Three are unsupported input-register-only
profiles in the current timing backend; this candidate has NOT been routed or
assigned an Fmax. No unsupported profile is treated as combinational by default.

A separate **mapped-netlist** experiment, `build-ddr-cpu-preg`, instead moves
MREG to PREG in the four frozen UART-prefix DSP cells, remapping CEM/RSTM to
CEP/RSTP. It does not rerun RTL synthesis. `build-cpu-dsp-preg-proof/results.json`
proves P, PCOUT, ACOUT and BCOUT by temporal induction with the actual Yosys
DSP simulation model and all four AREG/BREG profiles. The mapping checker
confirms that only P is observable in the actual design and all other cells,
connections, firmware and constraints are exact. Parent workload results are
composed with that mapped-cell proof; no fresh mapped-netlist workload simulation
is claimed. The copied synthesis script is provenance only and names parent
paths; it must not be rerun in the derived directory.

The new isolated CPU-PREG timing backend and independent model use the existing
DS182 AB-to-PREG setup bound (5.89 ns), PREG clock-to-P bound (0.45 ns), and CEP/
RSTP setup/hold rows, retaining A/B input-register checks. The output register
changes position, not pipeline depth. Profile tests pass; disabled replay is
running before candidate routing. All other timing-model/signoff limitations
remain in force.


### Captured predicates after the DSP output-register mapping

The PREG backend's disabled replay and profile regression completed successfully.
`build-ddr-cpu-preg-v2-weight40-route/seed-4` is the retained expanded diagnostic:
11.776/11.776/11.776 ns, native 84.92 MHz system / 91.41 MHz CPU. Seed 8 is
12.081/12.081/12.381 ns. Both integrity audits pass; full timing remains rejected.

`build-ddr-cpu-preg-wb-select` captures the existing two-bit DRAM region predicate
with the exact address-register clock, enable and synchronous reset. Actual
FDRE/LUT2 induction passes after common reset, and undoing the one-LUT/one-FF
transformation reconstructs the parent JSON exactly. Fresh seeds 4 and 8 yield
12.113/12.113/12.113 and 12.059/12.059/12.459 ns. Their integrity audits pass;
neither replaces the retained candidate. All copied synthesis scripts in these
derived directories are provenance only and retain parent paths.

`build-ddr-cpu-preg-mode` instead captures signedness predicates with the existing
seven instruction FFs. Their mixed FDPE/FDCE reset value is 11 (both predicates
false). All 256 instruction/sign combinations per old LUT cone are checked.
Actual LUT6/LUT2/FDCE models and the original instruction-register reset pattern
pass temporal induction after reset, including arbitrary new instructions.
Only three DSP cells' sign-extension inputs are rewired; eight new cells are
added. Every other existing connection is exact. Parent workloads are composed
with these proofs; no fresh mapped-netlist workload run is claimed. Routing is
in progress. Digital async2sync proof does not establish analog reset timing.


Multiplier mode capture finished at 11.375/11.375/11.910 ns (seed 4) and
12.707/12.707/12.807 ns (seed 8); both audits pass, neither is selected. The
initial audit helper had a local-variable shadowing error before report output;
the v2 helper fixes it and verifies the same immutable artifacts.

`build-ddr-cpu-preg-unused-a` ties pure multiply A[29:25] to zero. Actual DSP-model
induction passes for all four input-register profiles; the mapping checks that
only P is observable and all other cell content is unchanged. The first proof
harness mistakenly made existing lower-A constants variable and correctly failed;
`build-cpu-dsp-unused-a-proof-v2` preserves all lower input constants and passes.
Both proof artifacts are retained. Expanded seeds 4 and 8 are 12.236 and
12.224 ns in all probes. CPU-only native 104.44 MHz in seed 4 is not SoC timing
closure; cross-domain DSP setup exceeds 10 ns. No promotion.

`build-ddr-cpu-preg-wb-lut` replaces the measured four-LUT command-enable cone
with one LUT6. Exhaustive truth-table evaluation covers all 64 independent cut
input combinations. The output net is unchanged and restoring the one cell
reconstructs the entire parent netlist exactly. Existing intermediate cells are
left for their other consumers. There are no state, firmware or latency changes.
Two route seeds are in progress.


The collapsed Wishbone LUT finished at 11.746/11.746/11.746 ns (seed 4) and
12.078/12.078/12.278 ns (seed 8). Both integrity audits pass. Seed 4 is the new
retained expanded diagnostic, native 85.51 MHz system / 106.13 MHz CPU. The
converter-state group falls from 11.776 to 11.192 ns; the new group trace starts
in state feedback. CPU-to-system DSP input is now the worst expanded path.
A same-edge signedness capture is being composed with the LUT change in
`build-ddr-cpu-preg-wb-lut-mode`, with its own actual-cone proof and fresh route.

`build-ddr-descriptor-ranges` is a fresh RTL/synthesis experiment. It splits
address-plus-length into a 17-bit low sum and independently calculated upper
comparisons. Formal equivalence covers all 96 address/length bits, including
invalid descriptors, overflow, adjacent buffers and overlap. Full inherited
proofs, smoke and 45-shape GEMM pass with every workload field and firmware
binary exact. Full Yosys synthesis passes. The original MREG profile is routing;
`build-descriptor-cpu-preg-proof/results.json` also proves all four newly
synthesized DSPs' PREG mapping for the derived `build-ddr-descriptor-preg`.
No additional CPU, DMA or descriptor cycle is introduced. Neither candidate has
a completed timing result yet.


The combined Wishbone LUT + multiplier mode capture regressed to
12.377/12.377/13.132 ns. The fresh descriptor-range RTL route is
13.422/13.422/13.622 ns; its PREG derivative is 12.435/12.435/12.635 ns. Full
functional fields remain exact. No candidate replaces 11.746 ns.

`build-ddr-cpu-preg-wb-exit-luts` composes a second exact six-input LUT collapse:
the five-LUT exit-code CE chain. `build-ddr-cpu-preg-timing-luts` independently
selects twelve collapsible roots from the retained route's measured failing FF
endpoints. Each original acyclic cone has at most six independent inputs and
an exhaustive 64-row truth table; every replacement input is an original
ancestor. Composition changes no state or cycle and preserves every original
output function. The full netlist restores exactly when replacement cells are
undone. No fresh mapped-netlist workload run is claimed. Routing/model checks
are pending, as are extra retained-candidate seeds 2 and 5.


The exit-code LUT collapse finishes at 12.078 ns in all probes. The twelve-root
LUT-collapse experiment finishes at 12.138 ns in all probes; both integrity
checks pass and neither is selected. Extra retained-candidate seed 2 is
12.219/12.219/12.419 ns; seed 5's worst zero probe is CPU-to-system DSP input at
12.237 ns despite its 89.84 MHz native system report. The descriptor PREG
candidate's targeted batch-command-error group is 9.685 ns, compared with the
traced 11.910 ns example before the narrow range rewrite; whole-design timing
still regresses, so the rewrite is not promoted.

The optional domain-criticality aggregation backend, its regression tests,
disabled byte-exact replay and enabled route experiments are documented in
[DOMAIN_CRITICALITY.md](../carry-guidance/DOMAIN_CRITICALITY.md). No timing model,
clock constraint or acceptance threshold changes. The disabled reference is
reproduced exactly before enabled placement is attempted.


Domain criticality enabled seeds 4 and 5 finish at 12.293/12.293/13.006 ns and
11.858/11.858/11.858 ns, respectively. Both specialized integrity audits pass;
no all-column candidate replaces 11.746 ns. The all-column aggregate stage 15
verifies 45 routes and 3,199 hashes.

The [stock KC705 column experiment](../carry-guidance/KC705_GRADE.md) preserves
all-column results and separately verifies the stock -2 / 1.0 V column from
UG810, DS182 and repository configuration. Seed 5 of the unchanged retained
netlist becomes 11.448/11.448/11.572 ns under these selected primitive limits;
22,460 CLOCK rows change, with identical ports, net arcs and combinational arcs.
This is a model comparison, not a new route or measured hardware improvement.
The grade-column native backend passes exact disabled replay and is now routing.

`build-ddr-cpu-preg-sign-luts` factors the original multiply sign cones without
adding registers: one LUT5 recognizes the common upper instruction bits, and
two LUT4s combine the low instruction bits and operand signs. Every original
instruction/sign case passes exhaustive equivalence (256 per operand), and
restoring the two cells/removing the added LUT restores the entire parent JSON.
A fresh grade-column seed-5 route compares this candidate with its parent under
identical placement weight/density and unchanged 100 MHz constraints.
