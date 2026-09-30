# Placement experiment result — 2026-09-09

**Disposition: reject `NEXTPNR_PLACER_BETA=0.6`; no production change.**
One targeted variant was screened with placement, then routed. The parent
baseline was consumed, not rebuilt. No second candidate was routed.

| Final routed metric | Parent beta .4 | Candidate beta .6 |
| --- | ---: | ---: |
| `soc.cpu_clk` Fmax, target 100 MHz | 6.29 MHz FAIL | 6.15 MHz FAIL |
| `clk` Fmax, target 100 MHz | 39.97 MHz FAIL | 40.15 MHz FAIL |
| `clk200` Fmax, target 200 MHz | 1324.50 MHz PASS | 1324.50 MHz PASS |
| `memory.iodelay_clk` Fmax, target 200 MHz | 665.78 MHz PASS | 744.60 MHz PASS |
| `clk` → CPU max delay | 6.98 ns | 7.32 ns |
| CPU → `clk` max delay | 14.83 ns | 14.93 ns |
| CPU critical-path logic / routing | 27.8 / 131.2 ns | 24.4 / 138.3 ns |
| CPU critical-path arc count | 194 | 162 |
| CPU critical-path tile bbox | (76,263)–(144,340) | (134,183)–(188,313) |
| CPU critical-path summed Manhattan distance | 1,915 tiles | 2,198 tiles |

These are each design's worst paths; their endpoints differ, so the logic and
routing differences are not measurements of the same path. CPU Fmax regressed
approximately 2.2%. Candidate start is `$auto$ff.cc:337:slice$64244.Q`, net
`soc.cpu.id_ex_inst0_rs1_addr_out[1]`; end is `$auto$ff.cc:337:slice$97428.D`.
Baseline endpoint aliases are WB instruction ID bit 0 → EX/MEM execution
output bit 28. The baseline includes the combinational divider chain.

The candidate's earlier placement log showed 6.02 MHz CPU and 45.70 MHz `clk`,
but the placement-only **post-legalisation** JSON reported 5.69 / 39.44 MHz.
This confirms that early log Fmax should not select a candidate. Placement
checksum `0xad488d89` matched between the screening run on the supplied binary
and the full candidate run on the private two-worker executable.

Both runs retain the original XDC warning at line 486:
`set_property: target get_iobanks not supported`. `DCI_CASCADE {32 34}` on bank
33 is still in the XDC, and its unsupported status is not waived. Input is
200 MHz, sys/CPU 100 MHz, DDR outputs 400 MHz, idelay 200 MHz. Lack of a 400 MHz
interior-path Fmax entry is not a DDR interface timing signoff. Both routes
are diagnostic, fail system timing, and are not physically ready.

## Artifacts

- Parent log: `/Users/siriboi/github/tiny3tpu/build-ddr/synapse-current-baseline.log`
- Placement probe: `/tmp/synapse32-placement-density060-hvbodl6y/`
- Candidate final route: `/tmp/synapse32-placement-density060-c0g0tufe/`
  (`nextpnr.log`, `console.log`, `report.json`, `routed.json`, `manifest.json`).
- Private two-worker tool/source/build manifest:
  `/tmp/synapse32-placement-tool-zZxhzJ/`.

The final run returned zero despite timing FAIL; the original netlist, XDC,
chipdb and executable hashes were unchanged at completion. No RTL or synthesis
input was edited; no instruction, CSR, reset, DDR geometry or protocol behavior
change was introduced. No FASM or programming step was requested by the runner.
DDR port widths remain DQ=64, address=14, bank=3 in the unchanged input netlist.

Input SHA-256:

```text
soc.json b88d70650670d63728c9121025309f5b1fd2c11e44fb8166e401e161d4426489
kc705.xdc e1c892563932bfae60eddf7253e123a06239bce6c2c1ac3928186ba00921f10c
kc705.bin d3d90cb680525dcf42b19dde35df9660ca7a9a48b5865bd33404129a2595b284
private nextpnr 7b4ac94698ab42c3ba267282d3b5d728fdeb34e93800ff6b7dcce978bc02c085
```

The capped tool batches the same four router2 quadrants in pairs and preserves
their RNG contexts; source change and exact compile/link method are documented
in README.md. This scheduling difference is a comparison confound. The parent
would need its own controlled baseline with that executable before attributing
a small difference solely to density. No adoption is justified here regardless.

The runner's completion recognizer was corrected after this run to recognize
`Router2 time` followed by final critical paths and zero errors; the two
`route_complete` booleans in this run's manifest were corrected accordingly.
Future runs also capture `report.json` Fmax explicitly in the manifest.

## Handoff

No additional parent logs are needed for this completed comparison. Hard CPU
rectangles remain unavailable through this supplied binary's exposed interfaces
because Python hooks are disabled. The connectivity analyzer and baseline
bounding box support a future region experiment once a callable region hook is
available; this result must not be described as a tested CPU hard floorplan.
The implemented and tested candidate uses the supported HeAP locality knob.
