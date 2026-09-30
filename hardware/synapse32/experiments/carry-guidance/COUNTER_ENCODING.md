# DDR occupancy-counter control factoring

The combined selector, DMA range guards and AW-ready collapse is
`build-grade2-selector-dma-dual-guard-ready/patch.json`. Its full fixed route
passes logical/placement integrity, but expanded probes are
10.781 / 10.781 / 10.877 ns (native system/CPU 91.94 / 101.25 MHz).
AW-ready FF70875 CE improves to 9.879 ns, and failing endpoint/domain pairs
fall to 174. DDR write-ID/write-data occupancy updates become the worst groups.
This route does not replace the retained 10.841 ns worst diagnostic.

`tools/synapse32_packed_counter_encoding.py` discovers all ten counter update
cones dependent on write-address-change and command-enable. The dependency
walk includes LUTs, muxes and carry cells; it rejects an unsupported
late-dependent primitive instead of treating it as an early cut. The observed
cones contain LUTs and MUXF7/MUXF8, with 6–11 cut inputs. For each output, the
earlier inputs select one of six functions of the two late controls. Three
encoded bits plus those controls fit a final LUT5. The early encoders contain
no dependency on either late result.

All 7,616 cut cases pass, along with a ten-output SAT proof using actual Xilinx
LUT and MUXF7/MUXF8 models. This proof composes with the base patch's 13,376 cut
cases and 19-output primitive SAT. Every register's parameters and connections
remain unchanged. Placement-only constraints are detached from old mux macros;
unused original child cells remain at their original BELs. The router must
pass normal legality, exact planned placement and complete logical-port equality
against the proved patch. No clock period or execution cycle changes.

The initial dense encoding adds 81 LUTs beyond the 51 base LUTs. The full route
`build-grade2-counter-encoding-route` passes integrity but reaches
10.871 / 10.871 / 10.971 ns (native 91.15 / 102.09 MHz). Write-ID occupancy leaves
the failing list, but three write-data occupancy endpoints remain at up to
10.258 ns; whole-design failures rise to 211. DMA status FIFO length input is
the new worst. This layout is rejected.

`tools/synapse32_packed_counter_encoding_linear.py` searches injective
three-bit linear encodings of the four-bit function table. It evaluates all
three-mask choices, minimizes the deterministic LUT-decomposition cost and
support size, and independently rechecks every counter cut case and actual
primitive SAT. It reduces the added counter LUTs from 81 to 41. The route
`build-grade2-counter-encoding-linear-route` passes legality, exact logical
behavior and planned placements, native 92.12 / 99.16 MHz. Expanded probes are 10.855 ns each; the independent final audit passes.
The whole-design worst is TPU transport bridge response-code CE. Failures fall
to 134 endpoint/domain pairs, but three write-data occupancy endpoints remain
at up to 10.318 ns. The counter trace reaches address-change at 7.168 ns, then
spends 2.385 ns on the net to the final LUT, 0.200 ns in that LUT and 0.565 ns
on the final net plus setup. This remaining path is routing-dominated after
the comparison. The lossless replay passed: only pip-ID serialization changed, with exact native graph and Fmax. Corrupt encoder/final INITs and injection
of a late signal into an encoder are rejected by both versions' checkers.

Full physical timing remains unaccepted: generic/carry delays, clock skew/hold,
reset recovery/removal and DDR IO still lack qualification. Parent measured
workloads are composed with combinational proofs; no fresh workload run or
whole-RTL synthesis is claimed for these packed-netlist experiments.


The compatible-route reuse result
`build-grade2-counter-encoding-linear-cross-reuse` improves the retained worst
probe to **10.781 ns in all three probes**, native **92.76 / 97.32 MHz**.
Integrity passes, and all **19,171** imported route resource sets are unchanged.
Whole-design failing endpoint/domain pairs number **167**. This is the retained
stock-column diagnostic; the complete timing gate still rejects it. The worst
trace now ends at DDR read-response-valid FF79154 D. The remaining three
write-data occupancy endpoints are still 10.318 ns.
