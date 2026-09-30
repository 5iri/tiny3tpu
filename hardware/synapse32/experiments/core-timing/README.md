# Core and memory timing coverage correction

**No verified whole-SoC Fmax is available from the current open backend.**
The original 97.53 MHz result omitted registered DSPs, block RAM, distributed
RAM writes, and every carry-cell delay. The last omission is especially
material: all 662 used CARRY4 cells have zero exported internal arcs. Merely
classifying carry ports as combinational did not make their paths propagate.
The Kintex database has no cell-timing SDF directory, and `getCellDelay` returns
false on these carry lookups. No Artix timing data is substituted as a Kintex
signoff bound.

The new graph models cover:

- Four current CPU DSP profiles, including MREG outputs, optional A/B input
  stages, bypass C-to-P paths and PCIN-to-P cascade paths. Packed constant pin
  inversions are applied before checking fixed modes. Unknown live inputs or
  unsupported register configurations fail the model. The same implementation
  supports the separately proven PE PREG-only profile.
- All sixteen current boot RAM blocks, as described in [BRAM timing](../bram-timing/README.md).
- RAMD32 distributed memory: 3,576 physical packed cells, of which 2,603 have
  used outputs. Read-address paths remain combinational; write data, write
  address and enable acquire setup endpoints; outputs also acquire a write-clock
  origin. Unused halves/padded outputs are recorded separately. Active undriven
  input and unsupported clock/profile checks remain strict.

Bounds are parsed from the hashed [AMD DS182 datasheet](https://docs.amd.com/v/u/en-US/ds182_Kintex_7_Data_Sheet),
using maxima across the listed speed/voltage grades. Hold bounds are stored but
hold, clock skew and reset recovery/removal analysis have **not** been added.
The original generic FF timing and remaining I/O/clock modeling also need
validation. Neither graph connectivity nor a conservative bound for one
primitive establishes whole-chip signoff.

The CPU's MREG-to-PCOUT clock delay is not available in the Kintex sources used
here. It remains an explicit symbolic parameter. An available Artix SDF value
is deliberately not treated as Kintex evidence. The carry model identifies
11,336 missing dependencies by evaluating the CARRY4 mux/XOR Boolean function,
including local constant propagation and the packed PRECYINIT selector.
Dynamic pins remain independent; no reachable-state assumption or timing
exception is introduced.

`tools/synapse32_apply_core_timing.py` applies the supported models and reports
failed timing coverage. `tools/synapse32_core_timing_sensitivity.py` additionally
restores missing carry connectivity with symbolic delays; zero/one values
for PCOUT and zero/0.1 ns values for carry arcs are **sensitivity probes only**.
They are not measured delays, accepted bounds, Fmax values or setup closure.
The symbolic values and missing-arc provenance are retained in every manifest.
`tools/synapse32_route_timing_sensitivity.py` performs the same analysis on
hashed outputs from the graph seed driver.

The constant-aware sensitivity analysis of the old best local route
(`build-ddr-core-timing-sensitivity-mid2-constant-aware`) finds a 17.745 ns
system path even at zero substituted carry/PCOUT delay. Its path is from the
DMA read address register through burst sizing, subtraction and terminal
comparison to descriptor ready. The CPU-to-system maximum is 13.623 ns, ending
at store data. These findings replace the previous assumption that only
0.253 ns of timing work remained. The original 97.53 MHz is still reproducible
for its incomplete graph; it is not a useful whole-SoC ranking metric.

The missing data also prevents the symbolic PCOUT paths from establishing
100 MHz: even with zero carry delay, the old best placement would require
clock-to-PCOUT at most 0.078 ns for the observed downstream path. That is a
required budget, **not** an estimate of the unknown delay.

Thirteen primitive-model, graph and BRAM tests pass:

```sh
python3 tests/test_synapse32_primitive_timing.py
python3 tests/test_synapse32_timing_graph.py
python3 tests/test_synapse32_bram_timing.py
```

The next validated RTL probe is [DMA read comparison](../dma-read-compare/README.md).
The user has selected an open-source-only flow. Validated Kintex timing data
and completion of the open timing models are still needed to verify physical
100 MHz timing; no device has been programmed or board default changed during
these experiments.
