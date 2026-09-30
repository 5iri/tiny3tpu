# DDR write-data selector geographic replication

Retained diagnostic baseline: `build-grade2-timer-mid-zero-flag-route`,
10.358 ns across all three expanded probes. Physical 100 MHz is unclosed.

The joint carry / bank4 experiment completed integrity but regressed to
10.817 ns. Its worst path ends at native-port write-data register 68550;
4.807 ns of that path is the final selector-to-register net. Selector LUT229056
feeds 16 D inputs distributed over SLICE rows 27 through 137. Earlier replicas
covered neighboring selectors 229059 and 229060 only.

The new candidate starts from the retained baseline and duplicates LUT229056
for two receiver groups: rows below 60 and rows 60 through 109. The upper
receivers keep the original driver. Each replica takes the original three
inputs and truth table. Original register D inputs select the equivalent local
output; all other cell fields remain exact. Placement minimizes the maximum
Manhattan distance to each group's receivers using unused, unshared LUT slots.
No register, pipeline stage, clock constraint or execution cycle is added.

Implementation: `tools/synapse32_packed_wdata_geographic_replicas.py`.
Validation reconstructs the parent transformation, checks the complete expected
replacement dictionaries and all eight actual LUT input cases, and rejects
mutations to LUT truth table, clock, reset, enable and initialization.
Routing uses the existing pin-preserving backend and original legality checks.
All expanded probes and final integrity must complete before comparison.

No timing improvement or fresh workload simulation is claimed by this plan.
The transformation is a packed-netlist experiment; generic/carry models,
clock skew/hold, reset recovery/removal and DDR IO still need qualification.

## Measured outcome

Proof passed: eight actual primitive cases, two replicas, eleven changed D
inputs, zero added state/cycles. All five deliberate mutations were rejected.
Routing and complete logical-port/placement checks passed. Native system timing
is 95.13 MHz; native CPU timing is 100.53 MHz. All three expanded probes are
10.512 ns, so this candidate is rejected and the retained baseline is unchanged.

The target FF68550 path worsens from 7.839 ns to 10.512 ns. Both paths launch
from FF68851 through LUT229025, LUT229023 and LUT229019. Routing from LUT229019
to the final selector increases from 1.680 ns to 5.010 ns; the selector-to-FF
route falls from 1.943 ns to 1.286 ns. This demonstrates that choosing replica
placement by receiver distance alone moved delay upstream and lost overall.
Any follow-up placement objective must include the actual input arrival times
and upstream drivers. This write-data path was not critical in the retained
baseline; priority returns to its DDR read-control/capture path.
