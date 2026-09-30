# Routed timing coverage audit

**Update:** the arc audit additionally finds all 662 carry cells untimed.
See [core timing](../core-timing/README.md) for the expanded models and current
limitations. The counts below document the original port-only audit.

The 97.53 MHz system / 101.68 MHz CPU result is a partial-model diagnostic.
The exact baseline tool omits registered CPU DSPs, RAMB36E1 timing and LUTRAM
write timing. It also uses generic 0.1 ns flip-flop setup/hold/clock-to-Q values
in `Arch::getPortClockingInfo`; classifying a port alone does not validate its
delay. None of these results establishes complete SoC timing closure.

The read-only [observer](observer.inc) exports actual port timing classes,
clocking records, cell delay arcs and per-sink routed delays from the live
nextpnr context during report generation. It does not alter placement, routing,
constraints or timing equations. Its isolated build replaces only the timing
object and hashes every original link input. The original executable remains
unchanged.

`build-ddr-timing-coverage-mid2/manifest.json` verifies an exact replay of the
best local placement: the entire routed JSON and reported Fmax equal the
parent. The exported graph SHA-256 is
`6d4f51bf45d666b6877caf51c782292c6747f37d14299f60ec0a5709e1e1d4c5`.

`coverage.json` checks that all 251,922 connected routed ports appear in the
live export. After excluding only constant-driver inputs and unused outputs,
it identifies these ignored dynamic ports among the internal datapath cells:

| Primitive | Cells with ignored dynamic ports | Ignored ports |
|---|---:|---:|
| CPU DSP48E1 | 4 | 399 |
| Boot RAMB36E1 | 16 | 1,600 |
| Distributed-memory SLICE_LUTX | 3,576 | 21,775 |

Ignored I/O, PLL, delay, serializer and clock-enable ports are separately
reported without granting exceptions or implying that all are data endpoints.
The audit does not equate missing clock/control classification with a specific
setup path; these require primitive-specific analysis.

The independent graph analyzer reproduces **all 998 reported endpoints at or
above 9 ns exactly**, including both crossing directions. All 194,222 active
graph nodes are visited; no combinational loop or dependent node is skipped.
It recovers the backend's integer picosecond delays before summation, avoiding
floating-point threshold discrepancies. The largest covered delays are
10.253 ns system, 9.835 ns CPU, 9.162 ns system-to-CPU and 9.918 ns CPU-to-system.

This analyzer can retain both clock-to-output and combinational origins on the
same output node, which is required by the CPU MREG-without-PREG DSP profiles.
Three independent algorithm tests exercise both origins, explicit cycle
reporting and picosecond recovery. This is groundwork for adding verified
primitive models, not a replacement for the missing models. No new Fmax is
accepted, and the DSP sweep now explicitly withholds full-SoC acceptance.

Reproduction (new output directories required):

```sh
python3 tools/synapse32_build_timing_graph_observer.py --out /tmp/timing-observer-new
python3 tools/synapse32_export_timing_graph.py \
  --parent build-ddr-route-local-ddr-mid-seed2/manifest.json \
  --reporter /tmp/timing-observer-new/nextpnr-xilinx --out build-timing-audit-new
python3 tools/synapse32_audit_timing_coverage.py --replay build-timing-audit-new
python3 tools/synapse32_analyze_timing_graph.py --replay build-timing-audit-new \
  --reference-endpoints build-ddr-endpoints-mid2-replay/endpoints.json
python3 tests/test_synapse32_timing_graph.py
```

Next work is primitive-profile and delay validation: registered DSPs including
PCIN/PCOUT cascades, boot RAM, distributed RAM and clock/reset checks. The
original RTL, firmware, throughput measurements and board defaults are unchanged
by this audit. DDR calibration/electrical validation remains outside simulation.
