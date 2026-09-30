# Lossless routing replay

The original unchanged routed-checkpoint replay aborted during import.
The backend emits wire-arrow pip names that its reader does not understand;
its SITEPIP reader also differs from the writer. A conservative opt-in decoder
found an ambiguous emitted name: SITEPIP/ODELAY_X1Y128/ODATAININV/ODATAIN
matches two pip entries. It failed closed; no arbitrary choice was made.

A separate backend build adds opt-in `PIPIDX/<tile>/<index>` names and exact
range-checked decoding. Original tools and timing artifacts remain untouched.
The binary is `/tmp/tiny3tpu-nextpnr-lossless-route-names/nextpnr-xilinx`;
`tools/synapse32_build_lossless_route_names.py` records its build and hashes.
Recovery archive: `build-toolchain-recovery/lossless-route-names-tools.tar.gz`.

Full routing of the unchanged best candidate with lossless names reproduces
all cells, settings, ports, routed wire sets and strengths, and the entire
raw timing graph exactly. Only pip-name spelling differs in the routed JSON.
Evidence: `build-grade2-lossless-routing-control/iteration-integrity.json`.
This does not claim that an ambiguous old pip name alone identifies a unique
physical pip; the new representation preserves that identity explicitly.

The resulting checkpoint reloads without place/route and matches every
logical port, BEL and complete routed-name/wire/strength triple exactly:
45,314 routed nets. It exports 768,883 pip lines through the backend exporter.
Evidence: `build-grade2-lossless-routing-replay/manifest.json`.
Both invalid tile and out-of-range index controls fail with explicit errors.
Evidence: `build-grade2-lossless-route-negative-controls/manifest.json`.
Do not assume the older fixed-route index-pair export is lossless for every
site pip; the proved round trip is the new ROUTING representation.

Next first test rerouting an unchanged checkpoint with routes preserved,
then a bounded modified-net experiment. Verify normal legality, unchanged
physical pins on retained nets, full routing/connectivity and all timing
probes. Exact save/load is necessary but does not itself prove incremental
routing safe. No modified incremental route has yet completed.

Worst timing remains 10.318 ns. CPU/firmware behavior is unchanged by this
serialization-only control. Physical 100 MHz, model qualification, skew/hold,
reset and DDR IO/calibration remain unclosed.
