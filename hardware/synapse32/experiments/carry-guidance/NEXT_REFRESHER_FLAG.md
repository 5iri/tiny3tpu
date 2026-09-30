> Update: this flag and two timer flags are now implemented, proved and routed.
> Retained expanded best is 10.358 ns, 44 failing endpoint/domain pairs.
> Continue from `NEXT_CAPTURE_SHARED_PREDICATE.md`; the original specification below is history.

# Next: same-edge refresher predicate

The current cleanup candidate passes final integrity but misses timing:
`build-grade2-ddr-dead-macro-cleanup-route`, 10.749 ns in all probes,
88 failing endpoint/domain pairs, native 93.03/101.25 MHz system/CPU.
Best-period diagnostic remains the DMA count-flag route at 10.391 ns;
fewest-failing-pair layout remains `build-grade2-cpu-reset-tpu-dsp-near-route`
with 52 pairs and 10.557 ns. No promotion or physical acceptance.

A concrete state-proof feasibility result is complete:
`build-grade2-refresher-flag-feasibility/manifest.json` and its negative
controls. **This has not yet been inserted into the packed SoC or routed.**
The actual primitive proof passes bounded checking and induction length 1.
Yosys explicitly imports four zero source INITs and one flag INIT=1.
Wrong initialization, ignored CE hold, and ignored reset each fail proof.

## Exact observed cone

LUT `$abc$216920$auto$blifparse.cc:557:parse_blif$217672` is LUT4,
truth 51967 / 0xCAFF, output bit 54724. Inputs in I0..I3 order:

| Input | FF suffix | Q bit | D bit | CE |
|---|---|---|---|---|
| I0 | 67247 | 54777 | 138457 | empty = constant enabled |
| I1 | 66879 | 54779 | 135004 | empty = constant enabled |
| I2 | 79207 | 54736 | 199437 | empty = constant enabled |
| I3 | 79208 | 54773 | 55756 | 137083 |

All four are FDRE, INIT=0, X_FFSYNC=1, CK=156059, SR=50991,
with no inversion parameters. The installed `xilinx/pack.cc` explicitly
disconnects CE when tied to VCC. That source is hashed by the feasibility
manifest and backed up as `packer-ce-contract.cc` in its output directory.
The traced maximum across these four register inputs is 4.535 ns in the
symbolic-0.1 ns carry probe:
`build-grade2-ddr-dead-macro-cleanup-route/refresher-input-registers-trace.json`.

## Proposed implementation

Repurpose the original LUT217672 as a next-predicate LUT6. Its six inputs
are the four D bits above, CE bit 137083, and held Q3 bit 54773. Its truth
is already computed as `next_table` in the feasibility manifest:

    next_predicate = old_function(D0, D1, D2, CE3 ? D3 : Q3)

Add one FDSE, INIT=1, CK=156059, S=50991, CE always enabled. Its D is the
new LUT6 output on a fresh bit. Its Q drives **the old predicate net 54724**,
so the existing consumers and aliases need no rewiring. The old four
registers and their update logic remain untouched. This adds one redundant
internal FF, no extra LUT, and no architecture/execution latency. Existing
two DMA redundant count flags remain; report the extra state honestly.

Use the actual FDSE primitive/template and metadata, including SR role S
and X_FFSYNC=1. A verified INIT=1 FDSE template exists at FF78002, but do not
copy its CONSTR_* or placement metadata. Source FF CE=[] must explicitly
mean constant enabled as in the checked packer contract. Preserve reset
priority and the last source bit's CE hold in the new LUT truth.

**Do not put the new flag at the original LUT's FF site.** Original LUT217672
is SLICE_X119Y54/C6LUT; that slice already has FFs68458/68459 using different
clock 111297, reset 54283, and CE100273. Move the next-decode LUT and new FF
together to a legal FF-free slice near the sources/consumers, preserving
all other existing state. Full normal legality and routing must run.

## Evidence and audit requirements

Implement a new proof helper using the cleanup patch as its hashed parent.
Validate the actual source LUT/FF fields against the feasibility fixture;
reconstruct or exactly bind the primitive miter rather than trusting only
a passed flag. Verify every new LUT/FF parameter and port, same-edge invariant,
INIT=1, synchronous set, constant CE, and unchanged original state/IO.
Carry forward the cleanup's `removed_cells`/`removed_netnames` metadata so
route/normalization/final-audit cell-set checks remain exact. The earlier
24 removed cells are pure combinational cones with no remaining-cell or
top-port consumers; their structural guards and negative tests must remain.

Route with the same firmware, clocks, seed5/frequency100, pin preservation,
normal legality and routing. Audit the added flag's D/S setup paths and
all other endpoints, not only the old shared predicate path. No new workload
simulation or RTL promotion has occurred in this packed experiment series.
Physical hold/skew/reset and DDR IO limitations remain open.
