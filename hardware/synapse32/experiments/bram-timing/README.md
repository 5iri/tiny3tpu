# Boot RAM timing coverage

The optional graph model in `tools/synapse32_apply_bram_timing.py` covers the
sixteen current RAMB36E1 boot-memory blocks: TDP mode, two-bit port A reads and
writes, NO_CHANGE writes, no optional output register, no ECC/cascade, disabled
port B and a noninverted common A clock. It rejects other configurations,
live inactive-port inputs, undriven active inputs, unexpected output use and
inconsistent packed pin aliases. Constant reset polarity is checked after
undoing the primitive's packed inversion parameter.

Setup, hold and clock-to-output bounds come from the maximum over all six
speed/voltage columns in [AMD DS182 Table 34](https://docs.amd.com/v/u/en-US/ds182_Kintex_7_Data_Sheet).
The script verifies the hashed PDF/text evidence and parses the actual rows.
The bounds include 2.44 ns clock-to-read output, 0.65 ns address setup,
0.78 ns data setup, 0.48 ns enable setup and 0.54 ns write-enable setup.
The minimum listed internal BRAM Fmax is 372.44 MHz. This experiment evaluates
maximum data-path delay; hold, clock skew and reset recovery/removal remain
unverified. Stored hold bounds do not imply that hold analysis has run.

The model annotates only timing classes and clocking records in the exported
routed graph. Netlist, routed connections, route delays, placements and RTL
are unchanged. Read outputs remain synchronous even with DOA_REG=0: the
optional extra output register is bypassed, not the RAM's clocked read.

`build-ddr-bram-timing-mid2-v3` applies the model to the exact best local route.
The overall covered maximum remains 10.253 ns, but this uncovers an additional
**10.173 ns boot enable path**, from `req_addr[19]` to
`soc.boot_mem.0.6/ENARDENU`. The RAM read-origin maximum is 8.025 ns.
Both are system-clock paths. These are partial-model findings; other missing
primitive timing and generic flip-flop bounds still prevent full SoC closure.

The analyzer keeps RAM-origin arrivals separate from other launches on the
same clock, so a merge cannot erase a RAM path during targeted reporting.
Its updated implementation still reproduces all 998 original >=9 ns endpoints
exactly (`baseline-recheck.json`). Seven graph/model tests cover mixed DSP-like
origins, same-clock origin merging, explicit graph cycles, precision, known RAM
path delays, packed reset inversion and unsupported-profile rejection.

The structural coverage census's former “dynamic” total includes undriven
connected pins. In particular, unused port B has undriven address/data inputs;
those are classified here as inactive from the validated zero-width profile,
not treated as timed port-A endpoints. Every physical pin gets a recorded
modeling decision in the experiment manifest.

```sh
python3 tools/synapse32_apply_bram_timing.py \
  --replay build-ddr-timing-coverage-mid2 --out build-bram-timing-new
python3 tests/test_synapse32_bram_timing.py
python3 tests/test_synapse32_timing_graph.py
```
