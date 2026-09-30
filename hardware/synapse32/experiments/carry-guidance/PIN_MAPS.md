# Logical pin labels in fixed-layout routing

`build-grade2-unused-a-checkpoint-replay` reproduces the parent routed JSON,
native timing graph and Fmax exactly while exporting a pre-fixup checkpoint.
The first fixed-layout control preserves all 43,048 cell locations but its
strict packed comparison fails. A full routing control also fails that strict
comparison. Neither failed control is accepted as an optimization result.

The full control retains the actual nets but loses 13 logical pin labels:
ten constant-ground RAMD32 read-address labels and three constant-ground LUT1
input labels. No dynamic logical input changes or disappears after expanding
shared-pin labels. Other strict-comparison differences include shared physical
LUT inputs and multiple logical inputs represented by one physical pin.

`tools/synapse32_build_pinmap_preservation.py` builds an isolated backend at
`/tmp/tiny3tpu-nextpnr-pinmap-preservation`. Its optional
`TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS` change preserves `X_ORIG_PORT_*` attributes
on pins outside the routing permutation's source/destination set. Their nets
were never disconnected. Changed pins still use the original rewrite logic.
The original source, objects and executable remain unchanged.

Actual route controls:

- `build-pinmap-disabled-fixed-replay`: exact routed JSON, native graph and Fmax.
- `build-pinmap-enabled-fixed-replay`: only the 13 recovered labels differ;
  every other routed JSON field, including placement and routing, is exact.
  Native Fmax is identical. The graph changes because labels are restored.
- `build-pinmap-enabled-fixed-replay/control-integrity.json`: every logical
  cell, parameter, connection and non-placement attribute matches the original
  pre-fixup checkpoint. Every original LUT input and RAM read/write address,
  clock and enable remains mandatory. Shared logical labels are expanded;
  unmapped supplementary physical A1..A6 inputs are recorded separately and RAM
  A6 ties are checked. All state and IO cells are included.

The fixed route's native 88.10 MHz system / 105.82 MHz CPU is a diagnostic,
not a promoted improvement. Its independent expanded probes are
10.752/10.752/11.351 ns. The combined workload/logic/route/timing integrity audit
passes; the timing gate rejects. This metadata repair is not a hardware speedup
and does not validate generic delays, carry delays, skew/hold, reset or DDR IO.

## Bounded placement trials

`synapse32_grade2_fixed_placement_v3.py` uses the verified backend and compares
every logical port after shared-pin expansion. All original cell locations are
locked except explicit moves. Original placement validity, routing and pin
fixup still run. Parent-derived clock periods are restored exactly.

The ZQCS-control F7 macro rooted at `parse_blif$228225...mux7`, including its two
LUT children, moves from SLICE_X114Y32 to known sites containing only FFs:

| Trial | Destination | Result | Expanded probes (ns) |
|---|---|---|---|
| near | SLICE_X127Y38 | Logic and exact three-cell placement pass | 10.920 / 10.920 / 11.141 |
| mid | SLICE_X123Y31 | Original post-placement validity rejects | No routed result |
| mid-even | SLICE_X128Y32 | Logic and exact three-cell placement pass | 10.792 / 10.792 / 11.141 |

Both valid routes report 89.76 MHz system / 105.82 MHz CPU, and both combined
integrity audits pass. Their timing gates reject. The first valid move's timer
endpoint is 10.730 ns, now reached from bank-machine ready/control rather than
the original timer source. The overall 11.141 ns path runs from DMA byte-count
addition through descriptor range comparison into `write_pending`. The failed
mid trial is retained; no legality bypass or clock exception is used.
