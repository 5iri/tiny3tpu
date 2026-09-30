# Shared branch target and exception selection

The DMA-optimized seed-4 route is limited by CPU `exception_tval_q[6]`.
This experiment combines the six mutually exclusive branch conditions, then
shares the common taken-branch target, redirect and misalignment handling.
It does not add prediction, change branch decisions or add pipeline stages.

`prepare.py` copies the proven atomic-selection overlay. Only the branch case
in `execution_unit.v` changes. All surrounding priority, defaults, instruction
handling and registers remain byte identical.

`build-branch-select/results.json` proves every output of the actual old/new
branch case for arbitrary instruction ID, operand pair, PC, immediate, trap
vectors and delegation input. It includes target address, jump controls,
misalignment exception and tval, covering untaken branches and invalid IDs.
The proof harness extracts both cases directly from their hashed CPU sources.

The experiment was also proved independently on the retained atomic-word
overlay: `build-branch-select-base/results.json`. Both combinations pass
complete smoke/45-shape profile comparisons with unchanged instruction counts,
enabled CPU edges, system cycles and DMA traffic. Firmware and constraints
remain byte exact.

| CPU combination | CARRY4 | LUT6 | FDRE | Seed 4 probes (ns) | Seed 8 probes (ns) |
| --- | ---: | ---: | ---: | --- | --- |
| Atomic-select + shared branch | 625 | 6546 | 7411 | 15.259 / 15.259 / 16.159 | 14.181 / 14.181 / 15.081 |
| Original atomic + shared branch | 625 | 6531 | 7411 | 15.521 / 15.521 / 15.560 | 13.192 / 13.192 / 13.370 |

Probes are PCOUT/carry 0/0, 1/0, 0/0.1 ns, with explicit missing-model status.
Neither combination beats retained DMA-capacity seed 4 across the probes.
Route integrity is recorded in the corresponding `build-branch-select` and
`build-branch-select-base` directories. No CPU selection change is promoted.
