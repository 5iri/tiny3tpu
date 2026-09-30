# Standalone DSP placement slots

The inherited XC7 packer assigns every DSP root `BEL_LOWER_DSP`, including
roots with no cascade children. In the retained stock-column route, all four
CPU DSPs therefore occupy even-numbered sites in one column, spread across
`DSP48_X3Y22`, `Y24`, `Y28`, and `Y32`.

`tools/synapse32_build_free_dsp_slots.py` builds an isolated backend at
`/tmp/tiny3tpu-nextpnr-free-dsp-slots`. With
`TINY3TPU_FREE_STANDALONE_DSP_SLOTS` set, only roots with no parent and no cascade
children lose that artificial slot constraint. DSP logic, parameters, clocks,
timing models, cascade placement constraints and native legality checks remain
unchanged. The original tool and its sources are hash-checked and untouched.

`build-free-dsp-slots-pack-tests-v2/results.json` passes actual packer tests:

- The current SoC has 36 standalone DSPs. Only their slot constraint metadata
  changes; all other packed JSON content is exact.
- A separate two-DSP cascade fixture keeps both cascade cells and their
  constraints exact, while releasing the other 34 standalone DSPs.
- With the option disabled, packed JSON exactly matches the original backend
  for both fixtures.

The initial fixture helper assumed unused PCOUT ports survived synthesis. It
stopped before producing a fixture. The v2 helper explicitly adds the synthetic
PCOUT connection only to the isolated test fixture and verifies full structural
reconstruction. That fixture is never used as a workload candidate.

`build-free-dsp-slots-disabled-replay/manifest.json` also passes a complete
disabled replay: routed JSON, native guidance graph and Fmax exactly match the
11.093 ns guarded-branch/unused-input reference. The enabled full seed-5 route
completed with 19 DSPs in upper slots, including three CPU DSPs. Original native
placement/routing legality checks passed. Its expanded probes are
11.599/11.599/11.740 ns, native 85.18 MHz system / 91.53 MHz CPU, so the option
is not selected. Integrity passes and the full timing gate rejects. Allowing
more physical sites does not guarantee a better placement.

Separately, `build-grade2-guarded-branch-checkpoint-replay/manifest.json` passes
exact routed JSON, guidance-graph and native-Fmax replay while exporting a
pre-fixup checkpoint. This is preparation for future bounded placement edits,
not an incremental timing result. Final routed JSON cannot simply be reimported
without accounting for packed-pin legalization and clock derivation; see
[the earlier rerouting checks](../REROUTE.md).
