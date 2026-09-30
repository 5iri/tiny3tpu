# Proved logic edits with fixed placement

The jump-address decode can now be edited directly in the packed netlist.
`tools/synapse32_packed_jump_patch.py` replaces the actual LUT2/LUT2/LUT3 cone
at cell suffix 220998 with a LUT5. It verifies all 32 independent inputs.
Every other cell, net and register is unchanged. The checker rejects altered
truth-table entries and input-net substitutions.

`build-grade2-choice-checkpoint-replay` reproduces the retained seed-5 route's
complete routed JSON, native timing graph and clock reports exactly while
exporting a placement checkpoint. Both routes below bind every cell to its
original final BEL and run normal placement legality, routing and pin fixup.
The unchanged control compares every logical cell/port; the edited candidate
compares against the exhaustively proved patch. No cells move in either run.

| Route | Expanded probes, ns | Jump-address endpoint, ns |
| --- | --- | --- |
| `build-grade2-choice-fixed-control` | 11.173 / 11.173 / 11.533 | 9.290 |
| `build-grade2-choice-fixed-jump` | 11.368 / 11.368 / 11.728 | 9.595 |

Both integrity audits pass. Both timing gates reject. The patch is not
selected, and the retained best worst probe remains 11.038 ns. All clock
periods and firmware bytes remain unchanged. Cycle preservation composes
parent workload evidence with combinational equivalence; no fresh workload
simulation or whole-RTL synthesis is claimed.

The first routing-reuse control exposed that the placement checkpoint has
only blank `ROUTING` values: it contains zero actual wire routes. Keeping those
values reproduces the unchanged control's routed JSON and native graph exactly.
`build-grade2-choice-routing-reuse-control/reuse-observation.json` records this;
it does not establish wire reuse.

A separate optional post-route exporter now captures after routing and before
pin-label fixup. It must reproduce the complete original route and native
graph exactly, and contain over 40,000 nonempty routing records, before any
routing-reuse experiment uses it. Its enabled replay passes with 45,271
routed-net records, exact routed JSON, native graph and clock reports. Its
logical cells also match the earlier placement checkpoint exactly.

The stock backend now has a separate lossless pip-ID serialization build.
Its replay changes only pip IDs appended to saved routing names; removing
those IDs recovers the identical complete routed JSON, and the native graph
and clocks are exact. This reuses the repository's existing unique-pip reader,
composed with stock timing, post-route observation and the opt-in pin-label fix.

Re-running the placer on the already legalized post-route checkpoint fails
validity at `SLICE_X120Y156/A5FF` (no cell). That attempt is retained as failed.
A separate unchanged-only control rejects moves and uses the original complete
route's placement-legality evidence, skips placement, and runs the original
router/pin fixup on the saved wires. This attempt failed in the constant-routing
pass because already imported constant wires were bound again. The next attempt
rebuilt clocks/constants, completed routing, but failed strict logic comparison:
`soc.serial.tx_fifo_tail[1]$LUT$8092` lost I0 and its A1 net changed from the
UART tail signal to GND. `logic-failure.json` records the concrete mismatch;
that route has no accepted integrity or timing result.

The v4 control imports only routes whose complete physical endpoint sets match
the final reference: 20,278 data routes qualify; 22,736 routes with incompatible
pins are rebuilt, along with clocks/constants. It passes the complete post-route logical comparison with zero cell moves.
Resource comparison finds that only 4,204 of those 20,278 imported routes
actually stay unchanged; the unlocked router changes the rest. In total,
14,458 of the original 45,271 routed-net resource sets are unchanged. The
comparison permits removal only of 81 aliases that have no physical routing
and no cell or top-level-port connections; it verifies those conditions.
Its expanded probes are 13.140/13.140/14.140 ns, worse than the retained
design. Integrity passes and its timing gate rejects. The second control
locks only the 20,278 compatible data routes; it passes complete logical
comparison and preserves every imported wire/pip resource set exactly.
In total, 30,372 of the original routed-net resource sets stay unchanged.
Its expanded probes are **10.781/10.781/11.038 ns**; native reports are
**90.60 MHz system / 100.53 MHz CPU**. Integrity passes and the complete timing
gate rejects. There are 311 failing endpoint/domain pairs, compared with 319
in the retained full-placement route. This matches the retained worst probe;
it does not establish full timing closure. These controls add no CPU cycles
or logic changes and are not default-design promotions.

Stage 16 verifies 31 fresh full-placement routes, six fixed-layout controls
or moves, one proved fixed-layout logic edit, two same-route reanalyses and fifteen
controls (1,584 hashes). Generic/carry delays, clock skew/hold, reset timing and
DDR IO remain unvalidated; there is no physical timing acceptance.
