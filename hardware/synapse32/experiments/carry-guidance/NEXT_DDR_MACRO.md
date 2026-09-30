# Next bounded DDR mux experiment

Implemented and audited in `build-grade2-ddr-ready-macro-encoding-route` and
`build-grade2-ddr-ready-macro-pruned-route`. Both pass 256 cases, primitive
SAT and negative controls; the second encoder is pruned from five inputs to
three. Ready0 improves to 10.137 ns. Expanded global probes are respectively
10.620 / 10.620 / 10.714 ns and 10.620 ns in all probes. The proposal below
is retained as its original rationale, not as a currently pending action.

Seven further DDR bank valid-decoder collapses then pass 112 local cases and
joint primitive SAT. `build-grade2-all-bank-valid-collapse-route` passes final
integrity at 10.539 ns in all probes; the checked DFI p1/p2/p3 address group
is 9.743 ns. Read-valid encoding and two final capture OR8 simplifications
have now passed their local proofs; a combined route is being prepared.


Start from `build-grade2-cpu-reset-tpu-dsp-near/patch.json`, whose completed
route has 52 failing endpoint/domain pairs and 10.557 ns expanded probes.
Do not inherit the rejected second TPU DSP move or the NOR-only rewrite.
The best-period diagnostic remains `build-grade2-dma-count-flags-route` at
10.391 ns; it is a distinct layout.

The observed ready path traverses sparse MUXF8 macro `$233945...mux8`.
Exploratory truth-table evidence is preserved in
`build-grade2-ddr-nor-macro/next-macro-encoding-investigation.json`.
Its eight independent dynamic cuts are:

- Late: 105590, 105551, 105571.
- Early: 51762, 78893, 105610, 105612, 105704.

Across all 32 early assignments, the three functions of the late inputs are
0, 253 and 255. Encode them as 0, 1 and 3 respectively. Two LUT5 encoders
and one final LUT5 can represent this exact function; assign unused code 2
explicitly and verify the complete composed circuit. This is an exploratory
mapping, not yet an implemented/proved/routed candidate.

Required evidence: all 256 dynamic input cases, actual LUT/MUX primitive SAT,
negative output and constant controls, and exact provenance of the original
`$PACKER_GND_DRV` PSEUDO_GND output 241167. The ground cut is constrained to
zero only because the actual unchanged driver establishes it. Preserve the
six original macro children and all their logical ports; clear only the
obsolete relative constraints when replacing the MUXF8 root by a LUT.
Preserve all other original cells, clocks, firmware and architectural cycles.
Route with normal legality and pin fixup, seed 5/frequency 100, then complete
normalization, all expanded probes, coverage rejection and integrity audit.
Use new helper filenames; do not edit previously hashed proof tools.

The rejected NOR8-only experiment still passed exact equivalence: it reduced
macro 228224 to two LUTs with 256 cases and primitive SAT. Its route, after
undoing the second TPU DSP move, worsened globally to 10.941 ns at FF77637 SR.
Do not promote it based on the local simplification.
