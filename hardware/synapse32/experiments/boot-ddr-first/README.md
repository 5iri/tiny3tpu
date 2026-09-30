# Boot, DMA, DDR queue and branch timing experiments

These are isolated RTL candidates based on `build-ddr-dma-uart-reset`, the
best previously selected expanded-timing configuration. All runs use actual
KC705 Yosys synthesis and nextpnr placement/routing at the unchanged 100 MHz
target. Firmware and original XDC bytes are preserved. No hardware default or
sibling CPU source is changed.

**Physical 100 MHz remains unclosed.** Expanded intervals below use the same
BRAM/DSP/LUTRAM models and three symbolic `(PCOUT, carry arc)` probes: `(0,0)`,
`(1,0)`, `(0,0.1)` ns. They restore omitted dependencies but are not validated
device-delay bounds. Native nextpnr MHz is not a substitute for these checks.

## RTL changes and proof scope

- `prepare.py`: removes an irrelevant external-ready dependency from the local
  boot RAM enable; caches the DDR write first-beat predicate alongside the
  existing beat counter. Boot acceptance is proved for all addresses, reset,
  state and signed `BOOT_WORDS`; temporal induction covers first-beat state,
  including the 255-to-zero wrap.
- `terminal.py`: simplifies the DMA output terminal flag, composing the
  existing last-cycle and short-burst patches. Whole-DMA equivalence passes
  2,308 comparison points.
- `fifo.py`: expresses the DDR ID queue's five-bit increment/decrement as
  parallel lower-bit predicates and per-bit toggles. Induction covers arbitrary
  push/pop/reset, simultaneous activity and wrap; payload and pointers stay
  intact.
- `availability.py`: uses parallel toggles for the queued-write count and
  removes an addition before the write-availability comparison. Exhaustive
  combinational proof includes five-bit overflow, and counter transitions
  have temporal induction proofs.
- `address_advance.py`: splits aligned short-burst DMA address addition and
  remaining-byte subtraction into a six-bit low part and precomputed high
  alternatives. The general profile retains its original arithmetic. Exact
  arithmetic/range checks and whole-DMA sequential equivalence pass 2,127
  points, preserving all 2,108 state bits and ports as comparison boundaries.
  Combinational capacity-selection cones remain intact so the proof retains
  the bound on the transfer size. No state or output check is removed.
- `branch_predicates.py`: computes equality, signed-less and unsigned-less
  alongside the CPU's existing operand capture. The six branch conditions use
  these predicates without adding an execution stage or branch predictor.
  Operand/predicate sequential equivalence passes in both `SYSTEM_MUL` modes;
  the patch verifies that all remaining execution-unit text is unchanged.

No extra handshake, instruction, or execution cycle is introduced. Each
completed candidate passes fresh smoke and 45-shape CPU/DMA/TPU runs, comparing
**every** PROFILE, METRICS and DMA field against the baseline. Full diagnostic:
1,659,843 instructions / 2,084,686 CPU edges = **0.796208 IPC**, and
**11,544,608 system cycles**. Smoke: 106,588 / 142,895 = 0.745918 IPC,
789,205 system cycles. Firmware binaries are byte identical. These workloads
use variable-latency memory, not the physical LiteDRAM/DDR3 PHY; generated
board-controller edits have the separate proofs described above.

## Routed results

All rows below use seed 8 except where stated. `B` means boot plus first-beat;
subsequent rows add the listed change cumulatively. Route and model names are
given to make regressions as reviewable as improvements.

| Candidate | Expanded probes (ns) | Model directory |
|---|---|---|
| Selected UART-reset baseline | 11.936 / 11.936 / 12.105 | `build-ddr-uart-reset-guided8-timing-sensitivity` |
| B | 13.140 / 13.140 / 13.234 | `build-ddr-boot-first-timing` |
| B + terminal | 14.149 / 14.149 / 14.469 | `build-ddr-boot-first-terminal-timing` |
| B + terminal + ID queue | 13.125 / 13.125 / 13.325 | `build-ddr-boot-first-fifo-timing` |
| Same, seed 4 | 12.805 / 12.805 / 13.005 | `build-ddr-boot-first-fifo4-timing` |
| Above + availability, seed 8 | 13.023 / 13.023 / 13.177 | `build-ddr-boot-first-availability-timing` |
| Above + address advance | 12.326 / 12.326 / 12.526 | `build-ddr-boot-first-advance-timing` |
| Terminal + address advance only | 13.495 / 13.495 / 13.795 | `build-ddr-dma-advance-only-timing` |
| Combined + branch predicates, seed 4 | 12.376 / 12.376 / 12.376 | `build-ddr-boot-first-branch4-timing` |
| Combined + branch predicates, seed 6 | 12.720 / 12.720 / 12.920 | `build-ddr-boot-first-branch6-timing` |

For these rows the baseline remains the overall selection. Fixing a local
path can worsen placement elsewhere, which is why the entire design is routed
and ranked after each change.

The combined address-advance candidate does improve several named paths under
the **same 0/0.1 ns probe**:

| Path group | Baseline (ns) | Combined (ns) |
|---|---:|---:|
| Boot RAM inputs | 11.936 | 10.201 |
| DMA output last flag | 11.345 | 7.233 |
| DDR ID queue inputs | 12.105 | 10.335 |
| DDR first-beat outputs | 12.105 | 11.012 |
| DDR write queue inputs | 11.295 | 11.335 |
| DDR availability outputs | 11.570 | 10.581 |
| DMA address inputs | 11.030 | 8.977 |
| DMA remaining-byte inputs | 9.620 | 9.022 |

Evidence: `build-ddr-boot-first/parent-focused-v3.json` and
`build-ddr-boot-first-advance/focused-v3.json`, generated by
`tools/synapse32_focused_timing.py`. The new global worst path is a CPU branch
comparison feeding the jump target; this motivated the operand-capture
predicate experiment. Local group maxima are not whole-SoC Fmax.

The branch-predicate seed-4 route completes legally at native **80.80 MHz
system / 96.85 MHz CPU**. Its expanded worst path changes to CSR address
`memory.builder_adr[3]` through four LUTs into the DDR PHY bitslip-counter
enable, at **12.376 ns**. The boot-RAM group is 8.990 ns and DMA last-flag
group is 5.958 ns, but the DMA address group is 10.009 ns. Neither individual
path improvements nor the native CPU report make this a new overall winner.
Evidence: `build-ddr-boot-first-branch/focused4-v3.json`,
`build-ddr-boot-first-branch/iteration-integrity4.json`, and
`build-ddr-boot-first-branch4-coverage/report.json`.

Branch seed 8 fails post-placement legality at `SLICE_X120Y62/A5FF` and is
excluded. Its unmodified log and rejected manifest remain in
`build-ddr-boot-first-branch-route/seed-8`; no timing is reported for it and
no legality check is bypassed.

Replacement seed 6 completes legally at native **77.40 MHz system /
108.83 MHz CPU**, but its expanded worst probe is **12.920 ns**. A CPU-only
native pass therefore does not establish whole-system improvement. The
selected overall route remains the UART-reset baseline.

## Reproduction and provenance

Frozen drivers are `run_terminal.py`, `run_fifo.py`, `run_availability.py`,
`run_advance.py`, `run_dma_only.py`, and `run_branch.py`. They copy hash-checked
prepared sources; they do not regenerate a different LiteDRAM configuration.
Use a fresh output directory for every preparation/proof/route/model/check.

```sh
python3 hardware/synapse32/experiments/boot-ddr-first/run_branch.py prepare --out NEW_BUILD
python3 hardware/synapse32/experiments/boot-ddr-first/run_branch.py prove --out NEW_BUILD
python3 hardware/synapse32/experiments/boot-ddr-first/run_branch.py smoke --out NEW_BUILD
python3 hardware/synapse32/experiments/boot-ddr-first/run_branch.py gemm --out NEW_BUILD
python3 hardware/synapse32/experiments/boot-ddr-first/run_branch.py synth --out NEW_BUILD
python3 tools/synapse32_carry_guided_all_placement_seed_sweep.py --board NEW_BUILD/board --out NEW_ROUTE --seeds 8 --jobs 1
python3 tools/synapse32_route_timing_sensitivity.py --route NEW_ROUTE/seed-8 --out NEW_MODEL
python3 tools/synapse32_focused_timing.py --sensitivity NEW_MODEL --out NEW_FOCUSED.json
python3 tools/synapse32_check_soc_timing.py --route NEW_ROUTE/seed-8 --sensitivity NEW_MODEL --out NEW_CHECK
python3 tools/synapse32_boot_ddr_iteration_audit.py --candidate NEW_BUILD --route NEW_ROUTE/seed-8 --sensitivity NEW_MODEL --check NEW_CHECK --focused NEW_FOCUSED.json --out NEW_AUDIT.json
```

The timing checker returns **exit 2** while closure is rejected. The integrity
audit can pass with timing rejected: it verifies proof, functional and artifact
consistency and explicitly records `full_soc_timing_accepted: false`.

`python3 tools/synapse32_boot_ddr_iteration_summary.py --out NEW_SUMMARY.json`
verifies and ranks all **12 completed route/model pairs**, including the two
byte-identical backend comparisons, and retains the failed branch seed as a
separate rejected record. Current evidence is
`build-ddr-boot-first/iteration-summary.json`. Its selection uses the worst of
the same three expanded probes, never CPU-only or incomplete native MHz.

Historical `run.py` completed synthesis but failed while recording source
metadata due to its path parser. Its original routed diagnostic is retained;
use the later drivers with `shlex` source parsing for reproducible evidence.
The initial address-advance proof/debug directories are failed experiments,
not acceptance evidence. Superseded focused reports without `-v3` do not match
the final helper hash. No failed experiment is silently promoted.

Large completed artifacts may use transparent APFS compression. Their paths,
readable bytes and SHA-256 hashes are unchanged; compression records reside
in `build-ddr-boot-first/transparent-compression*.json`.

Further CSR, read-DMA, multiplier and native primitive coverage work is recorded
in [CSR_TIMING.md](CSR_TIMING.md), including complete regressions and unchanged
throughput. The 100 MHz physical timing gate remains unclosed.
