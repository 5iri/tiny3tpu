# Lossless nextpnr routing checkpoints

The local Xilinx backend exports ordinary pip names as `source->destination`,
but its reader expects older numeric names. Some exported SITEPIP names also
identify multiple resources, including resources with the same destination.
The original saved routes therefore cannot be unambiguously reimported.

The isolated `synapse32_build_routing_import_unique.py` build changes only
routing serialization and wire-name canonicalization. Each newly exported pip
includes the exact chip-database tile/index. Import checks its bounds and
requires the human-readable name to match that resource. Timing equations,
placement/routing algorithms, chip database and legality checks are unchanged.
Original source, objects and executable remain untouched and hash checked.

A fresh replay of the 97.53 MHz system / 101.68 MHz CPU layout produces the
same routed JSON after stripping only the new ID suffixes, and the exact same
timing graph. The saved routing roundtrip also preserves all 44,851 named
routed nets, resource IDs and binding strengths. These are serialization
checks, not new timing closure claims.

The first two reader experiments reject ambiguous names rather than choosing
an arbitrary pip. They are retained for diagnosis. Early comparison scripts
also rejected empty/whitespace ROUTING attributes; the v3 control handles
those attributes while requiring exact equality of the entire design.

Reproduction:

```sh
python3 tools/synapse32_build_routing_import_unique.py \
  --out /tmp/tiny3tpu-nextpnr-routing-import-unique
python3 tools/synapse32_routing_import_unique_control_v3.py \
  --reference build-ddr-timing-coverage-mid2 \
  --out build-routing-import-unique-control-mid2-v3
```

Use new output directories when rerunning; existing evidence is immutable.
`tools/synapse32_preserve_unique_routes.py` only retains nets with exactly
matching driver/sink physical pins, cell types and BELs. Constants and clocks
are rebuilt. The incremental driver retains the original 100 MHz constraints
and rejects placement changes, loop warnings and stale evidence.
