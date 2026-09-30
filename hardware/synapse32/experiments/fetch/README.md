# Isolated instruction-fetch reuse experiment

The default candidate retains the native no-ready CPU and one-outstanding
ready/valid bus interfaces. It adds 16 direct-mapped, demand-filled instruction
entries for the default SoC boot RAM at `0x80000000..0x8000ffff`. Original RTL,
divider overlay, CSR implementation, SoC, clock-enable primitive, firmware and
shared harnesses are unchanged. All experiment files/builds are in this folder.

`synapse32_memory_sequencer.sv` is a replacement source with the original module
name, ports and `RESET_PC` parameter; the optional `FETCH_ENTRIES` parameter
selects capacity. Compile it **instead of** the original sequencer. The supplied
runner performs this substitution without editing shared files.

## Behavior and boundaries

- A successful demand fetch fills one tagged entry. A hit in `ST_FETCH_REQ`
  registers `cpu_instr` and `step_pending` without issuing a bus request.
  Misses retain the original request/response sequence and backpressure behavior.
- `ST_STEP_EDGE`, the full `ST_SETTLE` cycle, data-operation sampling, alignment
  checks and load/store lane handling are retained. The fastest hit-only CPU
  edge interval is three system cycles. Repeated PC values never suppress data
  operations: their enables, addresses and values are sampled once per step.
- Any valid CPU store into the boot window invalidates the entire buffer before
  the request is issued, including byte/halfword writes. A failed store or fetch
  faults before any following step. Reset clears validity; RAM contents survive.
- No prefetch, neighboring-word reads, data caching or MMIO fetch reuse occurs.
  A redirect hits only on an exact valid address tag; otherwise it demand-fetches.
  Fetches outside the boot window retain their original bus side effects.
- This candidate assumes the default 64 KiB boot mapping and all boot writes
  passing through this port or a coordinated reset. The interface has no snoop
  for independent DMA/debugger writes. It is not a general coherent instruction
  cache for arbitrary remapped memory systems.
- The existing BUFGCE falling-edge CE contract is unchanged. A readiness drop
  after that sample still permits the already-armed CPU rising edge and then
  faults the sequencer. Neither `cpu_step` becoming low nor the sticky fault
  retracts that edge.

## Measured results

All numbers below are simulated system cycles, with the **divider CPU overlay**
in both baseline and candidate. The baseline uses the original sequencer and
original CSR/SoC. No forwarding, interconnect or placement overlay is included.

| Configuration | Directed 34-step workload | Actual CPU divider workload | DRAM → TPU workload |
|---|---:|---:|---:|
| Original sequencer | 352 | 318,748 | 4,981,249 |
| 2 entries | 252 | 140,986 | 4,954,206 |
| **16 entries (default)** | **252** | **140,378** | **4,780,728** |
| 64 entries | 231 | 140,378 | 4,773,221 |

Default reductions are 55.96% for the divider workload and 4.03% for DRAM → TPU.
The 64-entry variant saves only another 0.157% of DRAM workload cycles relative
to 16 entries, with four times the entries; 16 remains the modest default.
This is a capacity choice based on simulation, not a physical area/timing result.

The directed workload executes six stores and two distinct side-effecting loads
in every variant. Fetch requests fall from 34 to 15 with 16 entries (14 with 64).
The cycle measurement ends before reset/error/late-readiness probes.

The actual CPU test checks 1,067 divisions, 1,355 stores, one load, 1,068 divider
launches, 1,067 retirements and writebacks, one interrupt and 35,213 CPU edges
for both designs. It includes reset during division, interrupt cancellation and
MRET retry, dependent operations and taken-branch squashing. The existing gated
collision matrix also passes all 64 cases, including 24 interrupt-boundary and
40 fault-priority cases, with matching detailed results and 256 stores. These
runs use `GATED=1`, exercising the actual no-ready CPU through the sequencer and
the unchanged BUFGCE simulation model.

The shared DRAM harness checks all 35 signed GEMM results. Both designs perform
9,294 external reads, 8,400 external writes, 37,176 read bytes, 33,176 write bytes
and 17,694 completed transactions. Default baseline/candidate request stalls
are 5,955/5,959; response latency sums are 177,454/177,246 system cycles.

Both use workload `dram-selftest-gemm-5x11x7-v1` and memory model
`cycle-xorshift-193075ab-delay1to19-v1`. This preserves the exact stimulus code
and seed, **not** per-transaction delays: the RNG advances each system cycle,
so changed request timing changes the sampled delay. The divider test likewise
retains its original cycle-dependent backpressure and delays and operand seed
`0x521afe09`. These results are not physical DDR bandwidth or CPU IPC measurements.

## Tests and reproducibility

Run from the repository root:

```sh
python3 hardware/synapse32/experiments/fetch/run.py
python3 hardware/synapse32/experiments/fetch/run.py --entries 2
python3 hardware/synapse32/experiments/fetch/run.py --entries 64
```

Use `--suite unit`, `--suite cpu` or `--suite dram` for a subset.
`SYNAPSE32_SOURCE` may override the sibling Synapse32 source tree. The runner
expects `iverilog`, `vvp`, `verilator`, `cmake`, `riscv64-unknown-elf-gcc` and
`riscv64-unknown-elf-objcopy` on PATH. Recorded tools: Icarus 13.0, Verilator
5.046, GCC 15.1.0. There are two compiler jobs per Verilator build.

`run.py` freezes source snapshots before either build, hashes every input, and
verifies the snapshot remains unchanged. Its DRAM runner is a relocated copy
of the existing CMake harness with exactly one RTL source-path substitution.
The C++ harness is copied byte-for-byte; both runs have the same hash. Firmware
HEX equality, workload/model IDs, external traffic, completed transactions,
checked results and actual CPU architectural/edge counts are asserted equal.
Only system-cycle counts and cycle-sensitive latency/stall metrics may differ.

`fetch_tb.sv` independently scores every data operation and checks instructions
at CPU edges against mutable RAM. It covers repeated PC with distinct stores
and read side effects; redirects/revisits and direct-map conflicts; current-word
and cached-target modification via byte, halfword and word writes; reset with
modified RAM; request backpressure through acceptance; delayed responses;
fetch/read/write errors, including a failed boot-code store; upper boot boundary
and uncached MMIO fetches; and late readiness loss after a buffered-fetch CE
sample. A request must match the demanded PC or the outstanding data operation,
which catches speculative MMIO reads. Watchdogs and failed assertions exit
unsuccessfully. The original comprehensive sequencer test runs unchanged too.

Durable logs and manifests:

- [Default final run](evidence/all-16/evidence.json)
- [2-entry full run](evidence/all-2/evidence.json)
- [64-entry full run](evidence/all-64/evidence.json)
- [2-entry final directed suite](evidence/unit-2/evidence.json)
- [64-entry final directed suite](evidence/unit-64/evidence.json)

The final directed suites add the cached-hit late-readiness probe after the
capacity sweep. All five evidence manifests report unchanged snapshots and no
live input changes during their runs. Full build trees and immutable
snapshots remain in ignored `run-*` folders; manifests name their exact paths.
Earlier failed development runs are retained there and are not passing evidence.

Shared DRAM harness SHA-256 for all baseline/candidate pairs:
`74a93fc196dc26a813d79838ed0c41be128d992b7f7031746bbd6cb6f1bb012b`.
Identical firmware HEX SHA-256:
`1018f421b9729d9b90a641231d0fc07bda63dd66c7cfd9dc7cd3c9fe89bdc965`.
Default candidate RTL SHA-256:
`fdb04e814f7c73e15b5eaf8ea4380e48192270c815422b440f77eb9d036812af`.

No synthesis, board placement or route was run. There are no Fmax, post-route
timing, hardware stability or board-throughput claims. Physical cost and timing
of the tag/data lookup remain unmeasured.
