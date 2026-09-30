# Multiply carry-save reduction — not selected

Two carry-save levels reduce four shifted partial products to one 48-bit
carry-propagating sum at the existing result-register edge. Partial products,
operand capture, reset and CPU latency remain unchanged. `prove.py` proves
low/high results for arbitrary partial-product words and selector values;
reversing the transform restores every original source byte.

`build-mul-carry-save-proved` contains the proof and exact smoke/45-shape
comparisons. The tested composition adds this CPU overlay to UART reset control.
Synthesis eliminates all DSP cascade consumers but adds three CARRY4 and 100
LUT6 relative to UART reset control. Register and DSP counts remain unchanged.
Guided seeds 4/8 do not beat the retained UART reset candidate across all probes:
14.185/14.185/14.385 ns and 11.840/11.840/12.855 ns, respectively. Neither is
selected. Native system MHz are 69.52 and 77.79 under symbolic carry guidance.

`tools/synapse32_route_timing_sensitivity_csa.py --expected-cascades 0` handles
the verified absence of cascade consumers. It retains all primitive-profile
checks and requires the PCOUT=0/1 graphs to be identical when no cascade exists.
`build-csa-analyzer-control/compatibility.json` confirms byte-identical model
graphs, maxima and budgets versus the old analyzer on the unchanged control.
Equal-delay cascade trace tie selection may differ. This is still a partial
model with symbolic carry delays, not physical timing signoff.
