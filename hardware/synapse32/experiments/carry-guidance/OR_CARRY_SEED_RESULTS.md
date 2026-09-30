# OR / carry paired seed results

All six predeclared cases completed normal routing, seed metadata validation,
expanded probes, complete logical-port/placement equality and final integrity.

| Seed | OR only, worst ns | Carry + OR, worst ns |
| --- | ---: | ---: |
| 4 | 10.572 | 10.573 |
| 5 | 10.337 | 10.318 |
| 6 | 10.573 | 10.572 |

Neither new seed improves the retained 10.318 ns result. The carry candidate
has a 19 ps advantage in seed5 but only opposite 1 ps differences in seeds4/6.
Do not call this a robust gain. Both designs still fail 100 MHz; physical
model qualification, skew/hold, reset and DDR IO remain open.

The active runner is terminal and its final summary is
`build-grade2-or-carry-paired-seed-summary.json`. No further seed runs are
implicitly scheduled by that runner. No architecture or firmware cycles changed.

## Next approach: preserve unaffected routing

Read-only inspection found existing nextpnr support for imported ROUTING
attributes (common/nextpnr.cc), fixed route export/import and locked routing
(xilinx/arch.cc and common/router2.cc). Current drivers discard all old
ROUTING attributes and route the full design, so a local improvement can
change unrelated paths. Investigate a controlled incremental experiment.

First replay a completely unchanged routed design and require exact logical
ports, BELs and routed connectivity. Use the backend exporter to serialize
fixed routes: ROUTING contains pseudo/site pip names that cannot all be
passed verbatim to the fixed-route importer. The importer can warn and skip
unresolved pips or nets, and can resolve nets by topology; treat any mismatch
as failure, not as permission to continue. Clock, constants and special IO
require explicit handling. Do not change the binary used by completed runs.
Only after the unchanged replay is verified should an altered candidate
freeze its provably unchanged nets and reroute a bounded affected set.
No timing improvement or route-preservation success is claimed yet.
