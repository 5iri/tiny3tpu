# Carry connectivity for optimization — symbolic, not timing signoff

The current KC705 chip database supplies no CARRY4 internal timing arcs. The
independent expanded analyzer restores Boolean connectivity offline, but the
placer cannot use those dependencies. This isolated experiment also supplies
the dependencies during placement/routing, with an explicitly symbolic cost.
It does not establish Kintex carry delay bounds or whole-SoC Fmax.

`carry_support.h` computes exact dependencies for the four XOR/mux carry stages
with local constants and independent dynamic inputs. `test_support.cpp` checks
all 19,683 ternary input configurations against an independent truth-table
oracle, including sensitivity to each dynamic input. Routed integration checks
compare every used arc with the existing independent Python support analysis.

The fallback preserves every successful original chip-database lookup. It is
disabled unless `TINY3TPU_CARRY_GUIDANCE_PS` is set (0..1000 ps). No default
source, binary, chip database, netlist, XDC or clock target is overwritten.
Only `arch.cc.o` changes, plus the previously verified read-only timing observer.
The builder hashes all original link inputs and requires them to remain exact.

## First version — rejected

`tools/synapse32_build_carry_guidance.py` builds the first isolated version at
`/tmp/tiny3tpu-nextpnr-carry-guidance`. Disabled replay reproduces routed JSON,
timing graph and native MHz exactly. However, enabling fallback arcs while
CARRY4 cells are unplaced contradicts the backend's existing timing-port
classification (`TMG_IGNORE` before placement). Budget annotation then reports
4,812 pending ports as combinational loops and ignores them by its existing
default. Neither seed is selected; the raw logs are retained. Final graph
normalization/support checks succeed, but do not excuse the earlier warning.

Evidence: `build-carry-guidance-disabled-replay`,
`build-ddr-seeds-carry-guided-graph/seed-{4,8}`, and
`build-ddr-carry-guided{4,8}-timing-sensitivity`. Expanded intervals are
13.435/13.435/13.635 ns (seed 4) and 13.320/13.320/13.520 ns (seed 8).

## Placed-cell version

`tools/synapse32_build_carry_guidance_placed.py` emits a separate version whose
fallback additionally requires `cell->bel != BelId()`, matching existing port
classification. It preserves the first version's scripts, artifacts and hashes.
`tools/synapse32_carry_guidance_placed_replay.py` requires exact disabled replay;
this passes in `build-carry-guidance-placed-disabled-replay` against the original
DMA burst-limit seed-4 route.

`tools/synapse32_carry_guided_placed_seed_sweep.py` rejects any run whose raw log
contains a combinational-loop warning. It retains all original legality checks
and the 100 MHz target. The original unsupported `get_iobanks` warning remains.
The first corrected sweep uses UART local acceptance, seeds 8 and 4, and
100 ps per supported carry arc as an optimization heuristic.

For fair comparison, the driver retains the raw graph and removes only its
symbolic CARRY4 CELLARC rows into a normalized copy. PORT, CLOCK and routed
NETARC rows remain byte-identical. Removed connected dependencies must match
the independent support oracle exactly. The standard sensitivity analyzer then
applies the same BRAM/DSP/LUTRAM and three symbolic carry/PCOUT probes used for
all preceding candidates. Native MHz with added carry coverage cannot be ranked
against the original native report. Every full-SoC timing acceptance flag stays
false, independently of whether an optimization run passes its integrity checks.

Reproduce in fresh output directories (builders refuse to overwrite evidence):

```sh
python3 tools/synapse32_build_carry_guidance_placed.py \
  --out /tmp/tiny3tpu-nextpnr-carry-guidance-placed
python3 tools/synapse32_carry_guidance_placed_replay.py \
  --reference build-ddr-seeds-burst-limit-graph/seed-4 \
  --out build-carry-guidance-placed-disabled-replay
python3 tools/synapse32_carry_guided_placed_seed_sweep.py \
  --board build-ddr-dma-uart-local-burst/board \
  --out build-ddr-seeds-carry-guided-placed-uart-local-graph --seeds 8 4 --jobs 2
```

## Completed corrected sweep

Both seeds completed without combinational-loop warnings and matched all
10,924 required connected carry arcs against the independent support oracle.
Disabled replay reproduces the reference routed JSON, exported graph and native
MHz exactly. No original binary, source or link input changes.

| Route | 0/0 ns probe | 1/0 ns probe | 0/0.1 ns probe |
|---|---:|---:|---:|
| Original backend, UART local seed 8 | 12.510 | 12.510 | 12.710 |
| Placed carry guidance, UART local seed 4 | 12.398 | 12.398 | 12.552 |
| Placed carry guidance, UART local seed 8 | 12.732 | 12.732 | 13.032 |

The normalized expanded intervals select guided seed 4. Its native report is
80.30 MHz system / 98.91 MHz CPU with symbolic carry cost included. That native
report cannot be compared directly with 91.89/108.99 MHz from the original
backend, which omitted carry arcs. Neither establishes physical Fmax.

The longest zero-probe endpoint is UART `soc.serial.scr[0]` enable. At 0.1 ns
per carry arc, CPU `multiply_result[13]` is longest. The DSP cascade downstream
path already takes 10.967 ns with PCOUT delay substituted as zero, so this
route does not satisfy 100 MHz even in that partial model. RTL, firmware and
XDC are exactly the UART local candidate's; no new functional cycle is added.

Evidence: `build-ddr-seeds-carry-guided-placed-uart-local-graph/seed-{4,8}`,
`build-ddr-carry-guided-placed-uart-local{4,8}-timing-sensitivity`, and
`build-uart-local-burst-proof/iteration-integrity.json`. The last artifact checks
25 manifests, eight comparison routes, all variant graph hashes, exact
functional records, proof hashes and disabled replay. The two first-version
routes are historical rejected runs, excluded from selection.

## Consistent carry classification before and after placement

`tools/synapse32_build_carry_guidance_all_placement.py` builds another isolated
backend at `/tmp/tiny3tpu-nextpnr-carry-guidance-all-placement`. With guidance
enabled, both the fallback arcs **and** the CARRY4 port classification are now
available before a BEL is assigned. This fixes the API inconsistency in the
first version; it does not change the symbolic cost into a validated delay.
Successful chip-database lookups and disabled behavior remain intact.

The exhaustive 19,683-configuration carry-support test passes. Disabled replay
in `build-carry-guidance-all-placement-disabled-replay` exactly reproduces the
reference routed JSON, timing graph and native clocks. Original source,
binary and link inputs retain their recorded hashes. The new sweep rejects
combinational-loop warnings and records `initial_placement_carry_coverage`.

Two enabled comparisons completed without pending-port/loop warnings:

| RTL, seed 8 | New route directory | Expanded probes (ns) |
|---|---|---|
| UART-reset baseline | `build-ddr-uart-reset-all-placement/seed-8` | 11.936 / 11.936 / 12.105 |
| Boot/DDR/DMA address-advance candidate | `build-ddr-boot-first-advance-all-placement/seed-8` | 12.326 / 12.326 / 12.526 |

For **both** cases the routed JSON, raw guided graph and normalized graph are
byte identical to their placed-cell-guidance counterparts. This backend fix
therefore produces **no placement or timing improvement in these comparisons**.
The corresponding model directories end in `-all-placement-timing`.

```sh
python3 tools/synapse32_build_carry_guidance_all_placement.py --out /tmp/tiny3tpu-nextpnr-carry-guidance-all-placement
python3 tools/synapse32_carry_guidance_all_placement_replay.py --reference build-ddr-seeds-burst-limit-graph/seed-4 --out build-carry-guidance-all-placement-disabled-replay
python3 tools/synapse32_carry_guided_all_placement_seed_sweep.py --board NEW_BOARD --out NEW_ROUTE --seeds 8 4 --jobs 2
```

Use fresh destinations for reproduction. All full-SoC timing acceptance flags
remain false. See the [RTL iterations](../boot-ddr-first/README.md) for actual
critical-path edits and their throughput checks.


## Boot RAM, registered DSP and mixed LUTRAM follow-up

See [the primitive/mixed-output experiment record](../boot-ddr-first/CSR_TIMING.md)
for isolated native timing models, disabled exact replay, independent graph
comparison, and routed LUTRAM algorithm tests. `mixed_output_patch.py` preserves
both read-address and write-clock origins. The complete current-profile graph
adds 20,824 LUTRAM clock checks alongside RAM/DSP checks and symbolic carry arcs.
No physical signoff gap or 100 MHz failure is waived.
