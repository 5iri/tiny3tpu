# Fixed-placement rerouting toward 100 MHz

The selector-only seed 8 full route reaches 95.39 MHz system / 100.52 MHz CPU,
with crossings 9.10/9.82 ns. Its pre-routing placement is reconstructed using
the exact original command and inputs plus `--no-route`. The manifest at
`build-ddr-checkpoint-parallel8/manifest.json` confirms unchanged source hashes
and all 42,569 cell locations exactly matching the full route.

Importing final routed JSON directly failed on a post-legalization constant LUT
A6 pin. Those two trials (`build-ddr-reroute-parallel8-seed4` and `...-seed7`)
have no valid timing result. The pre-routing checkpoint imports successfully.

`tools/synapse32_reroute.py` removes only routing attributes, verifies complete
logic/placement identity, and routes with `--no-pack --no-place`. It checks
that the resulting cell locations remain unchanged. No functional tests need
rerunning for a routing-only change; the exact selector design already passes
full 45-shape profiles and component proofs.

Re-importing a checkpoint loses automatic PLL/buffer clock derivation. The
first successful reroute therefore lacked the original 200 MHz constraints
and is not counted. Current reroutes retain the original XDC verbatim and append
explicit clocks with the exact periods recorded by the parent's real derivation.
This restores the same half-period high/low model used by the packer, including
all 100/200/400/1600 MHz clock nets. It adds no relaxed clocks or timing exceptions.
All named nets must exist, parent inputs and checkpoint hashes must match,
and final reported clock targets are checked. The raw timing report is not
rewritten: missing automatic-derivation log notices remain; the actual parent
derivation is preserved separately in the manifest.

The restored-clock seed 4 result is **96.80 MHz system / 99.16 MHz CPU**,
with crossings 9.16/9.89 ns. All source hashes and placements are unchanged.
Evidence: `build-ddr-reroute-restored8-seed4/manifest.json`. This leaves roughly
0.33 ns system and 0.085 ns CPU setup shortfall at 100 MHz. The unsupported DDR
bank constraint and physical/calibration/clock-gating signoff limitations remain.

```sh
python3 tools/synapse32_reroute.py \
  --parent build-ddr-seeds-parallel-chooser-rest/seed-8/manifest.json \
  --checkpoint build-ddr-checkpoint-parallel8/placed.json \
  --out build-ddr-reroute-new --seed 7
```

The restored-clock seed 7 reroute gives 93.07 MHz system / 103.86 MHz CPU,
with crossings 9.10/9.82 ns. Reducing Router2 A* estimate weight from 1.75 to
1.0 at seed 4 gives 96.24/102.31 MHz, but CPU→system is 10.09 ns. Neither
beats the joint timing of the default seed 4 reroute (96.80/99.16 MHz).
All reported reroutes preserve placement and restore original clock periods;
routing settings are recorded separately and checked in exported JSON.

The full placement sweep through seed 16 also completed. Seed 13 reaches
96.20 MHz within the system domain, but its 10.84 ns CPU→system path limits
overall joint timing to about 92.25 MHz. It is not a better whole-SoC route
than seed 8. Its placement is nevertheless independently reconstructed and
verified as an alternative fixed-placement routing probe.

Latest best: restored seed 2 reaches **97.42 MHz system / 101.68 MHz CPU**,
with crossings 9.16/9.92 ns. Evidence: `build-ddr-reroute-restored8-seed2`.
This leaves about 0.265 ns system setup shortfall at 100 MHz.

## Isolated critical-sink router probe

`tools/synapse32_build_critical_sink_router.py` recompiles only `router2.cc` in
a separate output directory, then links it with the unchanged original object
files. The only source edit stable-sorts pending sink indices by descending
timing criticality before routing them. No arc is removed and no routing or
timing check changes. All timing/device code and the chip database stay fixed.
The build manifest hashes every original link object, library, source and binary
and confirms they were not modified. The reroute driver verifies that manifest
and the new binary/source/object hashes before using `--router-binary`.

Both routes completed with unchanged inputs and placement and restored clocks.
Seed 2 gives 93.07 MHz system / 101.68 MHz CPU; seed 4 gives 95.10/101.68 MHz.
Both regress against the original router best of 97.42/101.68 MHz. The modified
router is rejected. Original-router seed 5 also completed at 95.39/100.72 MHz.

## Local DDR placement experiment

The 97.42 MHz route has a long DDR refresh/command-to-bank-counter control
path. The candidate moves one complete ten-cell carry macro and one independent
reset-combining LUT into empty nearby slices. It changes no RTL or pipeline.

Re-running placement on the ordinary exported checkpoint is unsuitable: that
checkpoint already contains pin legalization (including RAM constant pins),
and the pre-legalization placer rejects even the unchanged baseline. The failed
`build-ddr-local-place-probe*` runs are not timing results. An initial pre-fixup
replay also allowed the standard repair pass to choose different locations;
those runs were rejected for unexpected movement.

`tools/synapse32_build_checkpoint_exporter.py` builds an isolated copy that adds
only an optional JSON export before `fixupPlacement()`. The original fixup and
all checks still run. The baseline binary and all original objects are unchanged.
`tools/synapse32_export_pre_fixup.py` verifies that the final output is exactly
the original checkpoint as JSON. Evidence: `build-ddr-pre-fixup-parallel8`.

`tools/synapse32_local_placement.py` applies the original final BEL locations to
this pre-fixup logic, then makes the recorded local moves. The original placer
runs at zero temperature with every cell already bound, checks legality and
relative constraints, and performs normal pin legalization. It requires exactly
the requested final locations and unchanged logical cells. The equivalence
helper follows `X_ORIG_PORT_*` mappings to distinguish physical pin permutation
from a logic change; it compares every cell, parameter, logical connection and
other attribute. Packed I/O cells are included. JSON reimport drops unused nets,
empty pins and top-level port declarations after I/O packing; these are recorded
representation differences, not removed circuitry.

The first eleven-cell move passes these checks in
`build-ddr-local-legal-ddr-near-verified`. The final provenance-complete near/mid
candidates both pass. Seed-2 near routing gives 96.86/101.85 MHz; mid gives
**97.53/101.68 MHz**, crossings 9.16/9.92 ns. The reset-LUT-only move gives
96.24/101.85 MHz. Inputs, requested locations and clock targets are verified.
The mid candidate is the latest small improvement; 100 MHz remains open.
Its worst path begins with the high-fanout reset net. Two standalone consumer-LUT
placement probes and another mid routing seed are being checked.

Additional full placement seeds 17–20 completed at system/CPU MHz:
17: 89.69/103.07; 18: 84.28/96.29; 19: 93.26/91.95; 20: 89.73/102.46.
None beats the best joint result.

The reset-consumer placement probes both completed at 96.86/101.68 MHz and do
not improve the best. Mid DDR placement with router seed 4 gives
96.80/101.68 MHz. The best remains mid DDR placement seed 2 at 97.53/101.68 MHz.
These three trials preserve logical cells, requested placement and original
clock targets, but are not retained as improvements.

## Reset-copy and endpoint diagnostics

The exact parallel reset-stage copy passes structural equivalence: primitive
kind, initialization, clock, enable, data and asynchronous preset match the
original FDPE, and collapsing its output net restores the original logical
cells. This adds no reset cycle. The original placer also validates the new
location. Digital equivalence does not establish analog metastability or
reset recovery/removal signoff.

A CPU-region copy serving 3,603 loads routes at 93.07/100.93 MHz (seed 2) and
96.82/101.68 MHz (seed 4). A single-critical-load copy routes at 93.78/99.18 MHz.
All regress and remain rejected experiments. Evidence:
`build-ddr-local-reset-copy`, `build-ddr-local-reset-copy-single` and their
corresponding route directories. No reset replication is promoted.

An isolated endpoint logger changes only diagnostic printing during report JSON
generation. Its replay must reproduce both the original Fmax and entire routed
JSON exactly. `build-ddr-endpoints-mid2-replay/manifest.json` passes both checks:
998 endpoints exceed 9 ns, and 28 fail their 10 ns budget, all system→system.
Misses are 0.002–0.253 ns. They cluster in CPU jump/trap output logic, DDR bank 5
timing controls, TPU core 1 `c_out[12]`, and a DDR adapter ready register. CPU
clock and related-clock crossings still pass. A second observer adds backward
path traces using the same timing data; it also requires exact route replay.

Direct reimport of final routed JSON did not work in this tool build
(`build-ddr-endpoints-mid2`, exception before a valid report). The diagnostics
instead replay the verified pre-routing checkpoint and observe the completed
route. That failed import is not a timing result.
