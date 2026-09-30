# DMA control and jump decode experiments

These experiments preserve the mapped state boundary, firmware and clocks.
They use the documented stock KC705 registered-primitive timing column, not
the all-column stress category. All timing gates currently reject.

| Candidate | Expanded probes (ns) | Targeted endpoint (ns) |
| --- | --- | --- |
| `build-ddr-dma-descriptor-choice` | 11.591 / 11.591 / 11.591 | write-pending D: 9.219 |
| `build-ddr-dma-jump-decode` | 12.312 / 12.312 / 12.312 | jump-address D: 8.430 |
| `build-ddr-choice-jump-decode` | 11.491 / 11.491 / 12.191 | jump-address D: 9.681 |
| `build-ddr-dma-fifo-reset-choice-v2` | 13.023 / 13.023 / 13.978 | tracked FIFO cell maximum input: 8.955 |

All use fresh seed-5 placement/routing, beta 0.4 and timing weight 40.
Their `iteration-integrity.json` records pass. None replaces the retained
11.038 ns best worst-probe result.

The descriptor rewrite is an actual-primitive SAT proof over 182 cut inputs.
The original 207-cell write-pending cone is equivalent to a narrow descriptor
predicate selecting between independent control cofactors. The implementation
adds 224 combinational cells, retaining old cells used elsewhere. The final
output net and all other original netlist content are exact. No register or
execution cycle is added.

The jump rewrite replaces three serial LUTs at mapped root 8278 with one LUT5.
All 32 independent cut-input combinations are verified by the mapper and
recomputed by the independent integrity checker. On the descriptor candidate,
the measured jump-address endpoint improves from 11.591 to 8.430 ns, but the
worst overall interval regresses because of a different placement.

The combined route exposes a reset-to-DMA-output-FIFO-WE path at 12.312 ns.
The next candidate, `build-ddr-dma-fifo-reset-choice-v2`, precomputes the output
for each reset value, using reset only at a final LUT3. Actual-primitive SAT
passes over 13 independent inputs; three LUTs are added and all state/cycles
are preserved. Its fresh route and integrity audit complete, but its worst
probe regresses to 13.978 ns, through DMA byte-count logic into framing
`tx_left`. The FIFO cell's maximum input interval is now 8.955 ns at DI1;
this is an upper bound for its WE interval, not a direct WE trace. There are
503 failing endpoint/domain pairs, versus 319 in the retained best route.
This candidate is not selected. The first helper attempt rejected Yosys
scope metadata; v2 explicitly verifies those records have no connections and
omits them. The failed attempt remains available.

These are mapped-netlist transformations. Workload preservation composes
actual parent workload measurements with exact combinational proofs; these
are not fresh whole-RTL syntheses or mapped-netlist workload simulations.
Generic primitive/routing delays, carry costs, clock skew/hold, recovery/removal
and DDR IO remain unvalidated. A target endpoint below 10 ns does not establish
whole-SoC closure.
