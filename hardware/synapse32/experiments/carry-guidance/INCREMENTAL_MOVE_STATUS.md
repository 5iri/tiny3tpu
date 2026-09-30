# Incremental write-address placement status

The best retained expanded timing result remains 10.318 ns. No new timing closure is claimed.

The first modified incremental experiment moves 13 original FDRE registers, releases their incident nets, and locks other routes using the verified lossless pre-fixup checkpoint. Logical-port equivalence is asserted before execution, and normal placement legality remains enabled.

Versions 1 and 2 fail placement because checkpoint-generated synthetic A6 constant ties are counted as logical LUT inputs on import. Version 3 removes only unlabelled A6 VCC ties on 6LUTs before placement; it requires logical equivalence and would require all removed ties to be restored after a successful route. It passes placement legality, then fails routing on arc 14 of memory.main_aw_ready, from SLICE_X113Y62/D6LUT_O6 to SLICE_X113Y77/CEUSEDMUX_OUT. The candidate is rejected, with no accepted routed output or timing improvement.

Evidence: build-grade2-incremental-write-address-move-v3/manifest.json and console.log; driver tools/synapse32_incremental_write_address_move_v3.py. Prior failed versions remain preserved.

Next step: identify routing resources needed by the failing CE arc and release a narrowly scoped set of neighboring signal routes. Retain exact logical equivalence, normal placement checks, preservation checks for all routes outside that set, and the expanded timing audit before accepting any candidate.

## First successful incremental candidate

Version 4 released a 3x3 interconnect neighborhood and advanced to another moved register's address-input routing failure. Version 5 released the bounded old-to-new register-bank corridor (interconnect X66..71, Y58..80), completed routing, and preserved 43,700 route aliases. Its exact logical check failed: placement remerge regenerated logical labels from physical indices. The exhaustive local LUT audit rejected 93 of the 245 changed logical descriptions, so v5 is not accepted.

The isolated opt-in placement-label replay backend preserves existing logical roles by signal through normal placement input merging. Version 6 uses that backend, passes normal placement/routing, exact logical equivalence, exact requested register placement, retained-route equality, and restoration of synthetic ties. No architectural cycle or register-count change is introduced. Tool recovery archive: build-toolchain-recovery/placement-label-replay-tools.tar.gz.

Expanded probes improve from 10.252/10.252/10.318 ns to **10.252/10.252/10.252 ns**. Native system Fmax is 97.54 MHz and CPU Fmax is 100.53 MHz. Failing endpoint/domain pairs decrease from 37 to 23. The new worst endpoint is FF79172/D, through DDR bankmachine4 address/decode logic to the ready path. All CPU-related expanded domains remain below 10 ns. See build-grade2-incremental-write-address-move-v6/iteration-integrity.json and all-failing-paths.json.

The 100 MHz objective is still unachieved. Model qualification, clock skew/hold, reset recovery, DDR IO/calibration, and hardware validation remain open; no new workload simulation was run for this placement-only candidate.

## Bank-4 single-LUT placement probes

Two completed routes move unchanged LUT226566 from SLICE_X118Y15/D6LUT to either SLICE_X115Y19/A6LUT or SLICE_X116Y18/B6LUT. Both preserve logical equivalence and all retained routes. Both expanded results are 10.297 ns in all three probes, so neither replaces the 10.252 ns candidate. The first destination reduces over-10-ns endpoint/domain pairs from 23 to 19 but regresses the maximum; the midpoint has 23. No coverage/signoff acceptance is claimed for these losing probes.

The first probe's ready-path trace changes its launch from FF77912 through LUT226566 to FF77905 through neighboring LUT226563 (SLICE_X118Y15/B6LUT). This is evidence that the early decode group has competing arrivals, not just one critical LUT. Next optimization should address that group or its common downstream route. Results: build-grade2-bank4-decode-placement-comparison.json; full trace: build-grade2-incremental-bank4-decode-move/ready-path.json. Both jobs and their timing analyses completed; no live jobs remain from these probes.

## Paired decode improvement

Moving LUT226566 and LUT226563 together to SLICE_X115Y19/A6LUT and C6LUT passes normal placement/routing, exact logical equivalence, preservation of all retained routes, expanded timing normalization and coverage checks. All three expanded probes improve to **10.218 ns**; native system Fmax is **97.87 MHz**. Over-10-ns endpoint/domain pairs fall from 23 to 18. Evidence: build-grade2-incremental-bank4-decode-pair/iteration-integrity.json and all-failing-paths.json. This is the new retained diagnostic candidate. No architecture cycles, logical cells, or firmware behavior changed; no new workload simulation ran.

A separate move of the complete LUT228226 mux7 macro from SLICE_X123Y26 to SLICE_X119Y22 also passes logical and route-preservation checks but worsens all three probes to 10.572 ns. It is not retained. The goal is still unclosed by 0.218 ns in the expanded diagnostic model; physical signoff and hardware validation remain open.

## DDR status-register placement improvement

Version 1 of the status-capture move failed placement on a mux select/X-input conflict at the grant-register site. Version 2 used the direct F8-to-BFF connection but exposed a similar conflict at the ready-register destination. Version 3 uses SLICE_X115Y33/DFF for FF79172, SLICE_X114Y46/DFF for FF79171, and the direct F8 connection at SLICE_X120Y50/BFF for FF76029. All legality checks remain enabled.

Version 3 completes routing and exact logical equivalence, preserves all retained routes, and passes the diagnostic evaluation/coverage audit. The new retained expanded result is **10.195 ns in all three probes**, with native system **98.09 MHz** and CPU **100.53 MHz**. There are 18 over-budget endpoint/domain pairs. Ready and read-valid paths improve to 10.141 ns and 10.111 ns. The worst endpoint is now FF69392/D (TPU transport bridge response_data[1]), followed by FF68249/D at 10.182 ns. No cells, architecture cycles or firmware behavior changed; no new workload simulation ran.

Evidence: build-grade2-incremental-ddr-status-capture-move-v3/evaluation.json, manifest.json, all-failing-paths.json and the associated normalized/timing/coverage directories. This candidate supersedes the 10.218 ns paired decode result for further optimization. The goal remains unclosed by 0.195 ns in the expanded diagnostic model, with physical timing qualification and hardware validation still outstanding. All jobs in this iteration completed.

## TPU response-control placement improvement

Moving unchanged LUT233415 from SLICE_X107Y119/B6LUT to SLICE_X107Y102/D6LUT passes normal placement/routing, exact logical equivalence, retained-route checks and the complete expanded diagnostic evaluation. The LUT drives 32 response-data inputs, all included in timing analysis.

The retained worst expanded delay improves from 10.195 to **10.182 ns** in all three probes; native system Fmax is **98.21 MHz**, CPU remains 100.53 MHz. Over-budget endpoint/domain pairs increase from 18 to 21, so this is an improvement in the maximum delay, not a reduction of every failing path. The prior 10.195 ns candidate remains available. No new workload simulation ran; no architectural cycles or logical cells changed.

Evidence: build-grade2-incremental-tpu-response-move/evaluation.json and all-failing-paths.json. The new worst path ends at FF68249/D, the DDR converter write-data FIFO input bit335, with a 4.376 ns final connection from LUT229053 at SLICE_X128Y137/B6LUT to SLICE_X141Y27/A5FF. Next investigate that register's full input/output locality and control compatibility before attempting relocation. Physical signoff remains incomplete. All jobs in this iteration are terminal.

## FIFO bit335 capture-register relocation

Relocating unchanged FDRE FF68249 from SLICE_X141Y27/A5FF to SLICE_X130Y133/DFF completes normal placement/routing, exact logical equivalence, retained-route checks and full expanded diagnostic evaluation. Its only output consumer is FIFO RAMD32 memory.storage_10.0.55/DPR0_1. Both sides were explicitly traced: register D arrival/setup is **6.495 ns**, CE 4.421 ns, SR 2.470 ns; RAM DI2 is **3.696 ns**, WE 5.757 ns and WA1 3.897 ns. The regular endpoints report omits paths below 9 ns, so the separate tracked endpoint check is necessary evidence.

The retained expanded worst result improves to **10.141 ns** for all three probes; native system Fmax **98.61 MHz**, CPU **100.53 MHz**. Failing endpoint/domain pairs decrease from 21 to 17. Top remaining status paths are ready 10.141 ns and read-valid 10.111 ns, followed by read-beat offset paths at 10.068 ns. No cells or architectural cycles added; no new workload simulation ran.

Evidence: build-grade2-incremental-fifo335-capture-move/evaluation.json, all-failing-paths.json and fifo335-endpoint-check.json. This supersedes the 10.182 ns candidate for further optimization. Physical timing qualification/signoff and hardware validation remain incomplete. All jobs in this iteration completed.

## Ready decode/register grouping

Moving only the final ready LUT and FF79172 together to SLICE_X115Y32/D6LUT and DFF completes routing/equivalence but regresses worst expanded timing to 10.256 ns: the early-to-final LUT connection increases from 0.150 to 0.630 ns, outweighing the shorter register connection. This losing case is preserved as build-grade2-incremental-ready-direct-capture.

Moving the early ready LUT as well, to SLICE_X115Y32/C6LUT, retains the short inter-LUT connection and direct final capture. The full group passes normal placement/routing, exact logical equivalence, retained-route verification and expanded evaluation. Ready capture becomes **9.776 ns**. The new global maximum is **10.111 ns** in all three probes; native system Fmax **98.90 MHz**, CPU **100.53 MHz**. Failing endpoint/domain pairs decrease from 17 to 15. The remaining worst path is read-valid.

Retained candidate: build-grade2-incremental-ready-group-capture/evaluation.json and all-failing-paths.json. No architectural cycles or cells added and no new workload simulation performed. Physical timing qualification/signoff remains incomplete. All jobs in this iteration completed.

## Read-valid grouping and shared beat-control relocation

Grouping the read-valid early/final LUTs and FF79171 at SLICE_X119Y48/A6LUT, B6LUT and BFF passes legality, exact equivalence and expanded evaluation. Probes become 10.031/10.031/10.098 ns; native system 99.03 MHz. This candidate still has 15 failing endpoint/domain pairs, dominated by shared read-beat control paths under the symbolic 0.1 ns carry probe.

Moving the unchanged shared control LUT217104 from SLICE_X115Y88/B6LUT to SLICE_X113Y78/C6LUT then passes the same complete checks and improves all three expanded probes to **10.031 ns**. Native system Fmax is **99.69 MHz**, CPU **100.53 MHz**. Only **4** endpoint/domain pairs remain over budget: read-valid 10.031 ns; two TPU c_out bits 10.025 ns; write-buffer level bit3 10.008 ns. No architectural cells/cycles changed and no new workload simulation ran.

New retained candidate: build-grade2-incremental-beat-control-move/evaluation.json and all-failing-paths.json. Intermediate read-valid evidence is in build-grade2-incremental-readvalid-group-capture. Diagnostic margin remains -0.031 ns; this is not physical signoff. Model qualification, skew/hold, reset recovery, DDR IO/calibration and hardware validation remain outstanding. All jobs in this iteration completed.

## TPU output-pair margin improvement

The upstream read-valid LUT228229 midpoint move passes equivalence but regresses worst timing to 10.070 ns, so build-grade2-incremental-readvalid-upstream-move is not retained.

Starting from the 10.031 ns beat-control candidate, moving the LUT225278/FF105019 and LUT225281/FF105016 pairs from SLICE_X90Y142 to matching C/A positions in SLICE_X90Y150 passes legality, exact logical equivalence, retained-route checks and complete expanded evaluation. Both targeted TPU outputs improve from 10.025 ns to **9.695 ns**.

The global worst remains **10.031 ns** in all probes, but over-budget endpoint/domain pairs decrease from four to **three**: read-valid 10.031 ns; write-buffer level bit3 10.008 ns; converter FIFO input bit143 10.001 ns. The last is a newly exposed small regression. The new retained candidate is build-grade2-incremental-tpu-output-pairs-move/evaluation.json and all-failing-paths.json; the prior beat-control route remains available. No architecture cycles/cells changed, no new workload simulation ran, and physical signoff remains incomplete. All jobs in this iteration completed.

## Single remaining diagnostic failure

Grouping LUT234308 and FF66897 at SLICE_X115Y124/C6LUT and CFF passes full placement/routing, exact logical equivalence, retained-route verification and expanded evaluation. The counter path is now below 9 ns (absent from the >=9 ns endpoint summary), and the formerly 10.001 ns FIFO bit143 path also clears 10 ns. The only remaining over-budget endpoint/domain pair is read-valid at **10.031 ns**, identical in all three probes. Retained candidate: build-grade2-incremental-buffer-count-pair/evaluation.json and all-failing-paths.json.

An alternate same-slice read-valid arrangement at SLICE_X119Y48/C6LUT, D6LUT and DFF passes equivalence but regresses to 10.059 ns. build-grade2-incremental-readvalid-cd-capture is preserved as a losing candidate. The retained arrangement remains A6LUT, B6LUT and BFF. No architectural cycles/cells changed; no new workload simulation ran. Physical signoff remains incomplete. All jobs in this iteration completed.

## Further read-valid probes rejected

The early bank-decode LUT226463 midpoint move to SLICE_X126Y38/A6LUT passes normal placement, exact equivalence and full diagnostic evaluation but worsens the maximum to 10.136 ns (build-grade2-incremental-bank2-decode-move).

Swapping the final read-valid LUT positions to B6LUT/A6LUT with AFF at SLICE_X119Y48 also passes all correctness checks but worsens the maximum to 10.147 ns (build-grade2-incremental-readvalid-ba-capture). Neither replaces the retained buffer-count-pair candidate: one failing endpoint at 10.031 ns, native 99.69 MHz. The already tested C6LUT/D6LUT arrangement also loses (10.059 ns). Further work should examine another compatible group location or the shared read-valid cone, rather than rerun these positions. No architectural cycles changed; no workload simulation ran; physical signoff remains unproven. Both new jobs and all analyses completed.

## Read-valid repartition prepared

A complete read-valid group relocation to SLICE_X109Y49 passes legality/equivalence but regresses to 10.136 ns, so build-grade2-incremental-readvalid-west-group is rejected. The retained route stays at 10.031 ns.

An input-arrival audit of the retained route preserves the exact global maxima and identifies late OR input A[7] (early I2, pre-fixup bit101596) arriving at the early LUT at 9.356 ns. Final direct input A[2] (final I4, pre-fixup bit101539) arrives at 8.646 ns. The proposed swap routes A[7] directly into the final LUT and A[2] through the early LUT, without changing LUT count, register count or architectural cycles. This is a routing hypothesis, not a timing gain yet.

build-grade2-readvalid-arrival-swap-proof/proof.json proves the two actual packed primitive functions equivalent for all 256 boundary input combinations, passes a Yosys primitive SAT miter, and rejects an intentionally changed-function negative control. Driver: tools/synapse32_readvalid_arrival_swap_proof.py. Input-arrival evidence: build-grade2-incremental-buffer-count-pair/readvalid-input-arrivals.json, generated with tools/synapse32_analyze_input_arrivals.py. Next apply the hash-bound two-cell connection swap to the incremental driver, release all changed incident routes, compare routed logic exactly to the proved candidate and every other cell to the retained logic, then run expanded timing/coverage. The candidate has not been routed. All jobs in this iteration completed; physical signoff remains incomplete.

## First sub-10 ns diagnostic candidate — physical goal still open

Applying the proved read-valid OR input swap to the retained placement completes normal routing, exactly matches every logical port of the proved candidate, and preserves all retained routes. All three expanded probes reach **9.997 ns**, and every reported domain interval is within its budget. Native system Fmax is **100.03 MHz**, CPU **100.53 MHz**. The modeled margin is only **0.003 ns (3 ps)**. No cells or architectural cycles were added.

Evidence: build-grade2-incremental-readvalid-arrival-swap/diagnostic-100mhz-milestone.json binds the route, proof, normalized timing, three probes and coverage report to hashes. The independent coverage gate remains **accepted=false**: 11,703 connected native dynamic ports are unclassified; primitive delays include unvalidated symbolic values; generic FF/LUT/mux delays, Kintex carry/cascade delays, clock skew/hold, reset recovery/removal and DDR PHY IO timing are not validated. No new workload simulation, bitstream or hardware test has run for this candidate.

This is the first verified native/expanded diagnostic 100 MHz milestone, not complete physical timing closure or completion of the user's broader goal. Preserve this candidate while addressing the recorded coverage/model/signoff gaps and validating the final image on hardware. All jobs in this iteration completed. The goal remains active.
