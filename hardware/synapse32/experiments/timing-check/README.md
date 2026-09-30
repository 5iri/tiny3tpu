# Full-SoC timing check: NOT ACCEPTED

Use `tools/synapse32_check_soc_timing.py` for the current SoC acceptance check.
It exits **2** when coverage is incomplete, delay/clock validation is absent,
or the expanded diagnostic exceeds the clock budget. Native Fmax is only an
informational field. No option converts assumed delays into validated timing.

## Concrete paths the earlier headline did not check completely

| Candidate | Actual traced path | Native graph problem | Expanded diagnostic |
|---|---|---|---:|
| Partial 100.29 MHz report | DMA write `addr_reg[1]` → `output_last_cycle_next` → flag register | Eight required carry connections on this path are absent | 17.773 ns with carry/PCOUT substitutions at zero |
| Best expanded candidate | `rst` → boot RAM `soc.boot_mem.0.6.WEAU1` | Write-enable is `TMG_IGNORE`, with no capture-clock timing record | 11.936 ns |
| Best expanded candidate, 0.1 ns carry probe | DDR `main_write_beat_count[5]` → write-count register | This path is present in the carry-guided graph, but its carry costs are assumed | 12.105 ns |

All three intervals are diagnostics under the recorded models, not measured
hardware delays or validated Fmax. The relevant same-edge budget is 10 ns.
The first path reaches 18.663 ns with the 0.1 ns carry substitution. Its
17.773 ns zero-substitution result includes the existing routed delays and
other modeled cell delays; zero is not a claim that real carries are free.

The original-backend candidate has 11,336 missing dependencies across 662
CARRY4 cells. Its four registered CPU DSPs, sixteen boot RAM blocks and
distributed-memory write timing also lack native coverage. Ignored-port
counts include clock/control pins and are not counts of independent data
paths. Constants and unused outputs are distinguished by the port audit.

The carry-guided candidate is different: its actual native graph includes all
10,924 required carry dependencies across 627 cells. Those optimizer costs
are symbolic; registered DSP/RAM omissions remain. The driver also saves a
normalized graph without the carry costs for model comparison. This checker
uses **`guidance-timing-graph.tsv`** for its actual native report, not that
normalized comparison graph. It independently reproduces each reported native
clock period from the selected native graph before auditing it.

## Evidence and reproduction

```sh
python3 tools/synapse32_check_soc_timing.py \
  --route build-ddr-route-reset-decode5-pe-seed4 \
  --sensitivity build-ddr-reset-decode5-pe4-timing-sensitivity \
  --out build-soc-timing-check-native100-final

python3 tools/synapse32_check_soc_timing.py \
  --route build-ddr-seeds-uart-reset-guided-graph/seed-8 \
  --sensitivity build-ddr-uart-reset-guided8-timing-sensitivity \
  --out build-soc-timing-check-best-expanded-final
```

Both completed with expected exit status 2. Use new output directories for
reruns. Each directory contains `report.json`, `native-carry-coverage.json`
and `native-port-coverage.json`. The report includes complete path witnesses,
missing native internal connections, launch/capture timing classes and clock
records, domain budgets, all model assumptions and input SHA-256 hashes.
The expanded graphs restore every required carry connection; delay validation
is still incomplete. No graph files, RTL, firmware or constraints are changed
by this check. Preliminary reports without the `-final` suffix are superseded.

Ten new gate tests pass, including omitted validation, unknown delays, missing
arcs, bad budgets and choosing the actual guided graph. The existing four
graph, six primitive-model and three BRAM-model tests also pass (23 total).

The 100 MHz SoC goal remains open. The next optimization targets on the better
candidate are the boot-RAM write-enable/reset path and DDR write-count update.
Verified Kintex carry/cascade and generic cell delays, clock skew/hold,
reset recovery/removal and DDR PHY I/O analysis remain required for signoff.
