# Placement density on the corrected control/payload candidate

This probe uses the exact `build-ddr-dma-control-payload/board` netlist,
firmware, original XDC, nextpnr executable and chipdb, with seed 4. Only HeAP
density changes from beta=0.4 to beta=0.6; the tool reports unchanged alpha=0.08
and spread scales 2,1. No clocks or timing exceptions change.

| Placement | CPU MHz | System MHz | System→CPU | CPU→system |
|---|---:|---:|---:|---:|
| Original beta=0.4 | 98.91 | 84.54 | 9.33 ns | 10.08 ns |
| Denser beta=0.6 | 81.67 | 71.32 | 11.07 ns | 15.18 ns |

Both runs fail 100 MHz and retain the unsupported DCI constraint warning.
The denser placement worsens every listed timing metric and is rejected.
Input hashes remained unchanged. Evidence is in
`build-ddr-placement-control-dense/manifest.json` and `route.log`.

```sh
python3 tools/synapse32_route_variant.py --parent build-ddr-dma-control-payload/board/route-manifest.json --out build-placement-new --beta 0.6
```

The helper requires a fresh output directory, verifies parent input hashes,
records the explicit placement environment, and uses the shared strict timing
report. This probe uses the same executable as its parent; it does not use the
older private two-worker executable described in the earlier placement study.
