# Clock-domain criticality aggregation experiment

The isolated backend is `/tmp/tiny3tpu-nextpnr-domain-criticality-v2/nextpnr-xilinx`.
It retains the exact CPU-PREG architecture object and all primitive/routing
models. `TINY3TPU_DOMAIN_CRITICALITY=1` changes only optimization priorities.
It does not change constraints, path arrival calculations or acceptance rules.

In the inherited `common/timing.cc`, `nc.slack.at(i) = slack` overwrites a net
user's earlier clock-domain slack. The subsequent criticality loop reads that
last domain's slack while normalizing against each domain's worst slack, then
also overwrites `nc.criticality.at(i)`. Maximum path length and domain worst slack
likewise retain only the last visited domain. Consequently multi-domain fanin
priorities can depend on domain iteration order.

The opt-in fix retains the minimum user slack, calculates criticality from each
domain's own required time and arrival, and retains maximum criticality across
domains. Path length uses maximum and domain worst slack uses minimum. Existing
intra-clock normalization and asynchronous-domain handling are unchanged. This
is not a new clock relationship, false path, multicycle exception or delay model.

`test_domain_criticality.cpp` uses the actual production helper. It checks all
six permutations of a three-domain example, worst-slack retention, original
single-domain calculations across boundary cases, and a zero-range guard.
The new backend passes these checks. With every optional feature disabled,
`build-domain-criticality-disabled-replay/manifest.json` passes exact routed
JSON, timing graph and native Fmax replay against the established reference.
The first build attempt failed because macOS `/tmp` path normalization produced
`/private/private/tmp`; the v2 builder resolves the parent path first. Both
attempts are retained. No timing result came from the failed compile.

The retained route's independently evaluated graph contains 73 endpoint pins
reached from both `clk` and `soc.cpu_clk`; see
`build-ddr-cpu-preg-wb-lut/domain-fanin-evidence.json`. This establishes relevance,
not an expected speedup or a claim that its single worst DSP input has two
origins. Fresh enabled seeds 4 and 5 are in
`build-ddr-wb-lut-domain-criticality-route`; expanded checks are complete: seed 4 is 12.293/12.293/13.006 ns; seed 5 is
11.858 ns in all probes. Both integrity audits pass and timing remains rejected.
Seed 5 improves its matching old run (12.237 ns), but the retained all-column
11.746 ns candidate is still better.

Reproduction:

```sh
python3 tools/synapse32_build_domain_criticality_v2.py --out /tmp/NEW_BACKEND
# The checked replay/route drivers intentionally bind the recorded v2 backend.
python3 tools/synapse32_domain_criticality_replay.py --reference build-ddr-seeds-burst-limit-graph/seed-4 --out NEW_REPLAY
python3 tools/synapse32_domain_criticality_seed_sweep.py --board build-ddr-cpu-preg-wb-lut/board --out NEW_ROUTE --seeds 4 5 --jobs 2 --timing-weight 40
```

No physical timing acceptance: generic logic/routing delays, clock skew, hold,
reset recovery/removal and DDR IO remain incompletely validated. Symbolic carry
and PCOUT probes retain their existing diagnostic scope.
