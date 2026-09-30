# Combined CSR + bootdecode experiment — 2026-09-09

The combined candidate improves system Fmax but regresses the CPU bottleneck.
Do not adopt it as an overall timing improvement or claim timing closure.
Exactly one full synthesis and one route completed; no baseline reroute,
divider integration, production/sibling RTL edit, CMake edit, or flashing.

## Final routed clocks

| Clock / target MHz | Parent baseline | Bootdecode alone | Combined CSR + bootdecode |
| --- | ---: | ---: | ---: |
| CPU / 100 | 6.29 FAIL | 5.37 FAIL | 5.00 FAIL |
| System `clk` / 100 | 39.97 FAIL | 44.47 FAIL | 50.87 FAIL |
| `clk200` / 200 | 1324.50 PASS | 1349.53 PASS | 1353.18 PASS |
| `memory.iodelay_clk` / 200 | 665.78 PASS | 299.85 PASS | 382.85 PASS |

Combined versus parent: system +27.3%, CPU -20.5%. Combined versus
bootdecode alone: system +14.4%, CPU -6.9%. These are single-seed whole-design
mapping/placement interactions, not isolated cell-delay measurements. There
is no routed CSR-only result to establish an independent CSR timing effect.
The CPU remains the limiting clock. Retain the isolated evidence for comparison;
the result does not support unconditional integration.

Final clocks were taken from `timing.json` and cross-checked against the log
after `Router2 time 75.00s` and post-routing legalisation. The earlier placement
CPU/system figures (4.58/50.44 MHz) are not final routed results.
The process exited 0 with one warning and zero errors, despite timing FAIL.
The original XDC remains byte-identical, including `DCI_CASCADE {32 34}`;
`set_property: target get_iobanks not supported (on line 486)` remains unresolved.
This is diagnostic only, with no DDR I/O, calibration, clock-gating, or hardware
signoff. No timing overrides, altered constraints, or bitstream generation.

The final system critical path starts at `soc.sequencer.state[0]` and totals
approximately 19.7 ns (2.8 ns logic / 16.9 ns routing). The CPU worst path starts
at `soc.cpu.id_ex_inst0_rs1_addr_out[1]` and totals approximately 200.1 ns
(25.6 ns logic / 174.5 ns routing). These are different worst paths from the
parent, not paired endpoint measurements. Cross-clock max delays are 9.18 ns
system-to-CPU and 17.05 ns CPU-to-system.

## Isolation and verification

`run.py` creates a unique `/tmp` directory and freezes the accepted
`../cpu/csr_exec.v` and `../interconnect/synapse32_dram_soc.sv` there. It changes
exactly those two source-list paths plus the JSON output path in
`build-ddr/synth.ys`. All other CPU sources, including the original divider and
decoder, remain selected. No global source or CMake substitution is made.
All synthesis/proof processes run serially (one job, below the two-job limit),
with OMP/OpenBLAS/VECLIB thread caps of two. Routing uses one process with the
specified original nextpnr binary; no custom router build or placement override.

Fresh proofs against the frozen overlays passed:

- CSR: all 65 equivalence points, `equiv_simple; equiv_status -assert`, with
  unrestricted instruction IDs and inputs. Two-state combinational proof.
- Boot controller: `equiv_simple; equiv_induct -seq 4; equiv_status -assert`
  for BOOT_WORDS 16384, 3, 32768, 1, 2, 536870912, 536870913, and 1073741824.
  The reviewed interconnect abstraction exposes RAM side effects and arbitrary
  shared read data, with unconstrained request/response timing and resets.
- Full Slang synthesis: `check -assert` passed. The source audit confirms the
  SoC differs only inside the boot decode; parameters, RAM initialization,
  state logic, peripheral logic, and interfaces are unchanged.
- Top ports are exactly identical. All 16 RAMB36E1 and 124 RAM32M parameter/INIT
  dictionaries match by instance name. Flip-flop, DSP, clock, and I/O primitive
  parameter/INIT multisets match, including counts. `audit.py` reproduces this.

These compose at unchanged module interfaces: the CSR replacement preserves
all outputs combinationally and the boot controller preserves transaction and
RAM controls; unchanged RAM processes preserve contents from identical INIT.
This is compositional evidence, not a full CPU/DDR sequential equivalence proof,
an array-content proof, or a four-state X-propagation claim. Parameter multisets
alone do not prove mapped wiring equivalence.

| Mapped cells | Parent | Bootdecode alone | Combined |
| --- | ---: | ---: | ---: |
| LUT1..LUT6 | 23450 | 23383 | 23174 |
| CARRY4 | 1998 | 1994 | 1992 |
| Flip-flops | 12901 | 12901 | 12901 |
| MUXF7 | 3524 | 3597 | 3650 |
| MUXF8 | 1483 | 1480 | 1549 |
| RAMB36E1 | 16 | 16 | 16 |
| RAM32M | 124 | 124 | 124 |

The six-carry reduction is consistent with the four boot comparator and two
CSR carry cells removed by the accepted candidates. Other LUT/mux deltas include
global ABC remapping and should not be attributed exclusively to local logic.

## Artifacts and hashes

Completed run: `/tmp/tiny3tpu-combined-lhxjpxns/`.
The frozen RTL, generated synthesis/proof scripts, all proof logs,
`synthesis.log`, `preservation.log`, `combined-audit.log`, `nextpnr.log`,
`timing.json`, and `soc_routed.json` are there. `evidence.json` in this directory
is the completed manifest copied from that run, including exact commands,
all source-input hashes, output hashes, and final clocks. All tracked input
and overlay hashes were unchanged at completion. `combined-audit.log` was
generated separately while routing; the current runner also invokes that
audit before routing for reproduction.

| Artifact | SHA-256 |
| --- | --- |
| CSR overlay | `1b2cd34cdc3f648a54198105f498eeea7296c969e5272734dcb6c85a11afa76c` |
| Bootdecode overlay | `bb4c897a22647dcac9f3254e34cc32e2ea57094b3b2d57a72df5c6fa29a07a52` |
| Original divider | `2a714c59fb62259c69b1a1976a331e8a56ba9299b404bd4d289e2ed4e01434d6` |
| Baseline netlist | `b88d70650670d63728c9121025309f5b1fd2c11e44fb8166e401e161d4426489` |
| Combined netlist | `df7446dbdc7e737e7b0c0ed689b6ecb43f7ac4b12d793521188b3e4d5838a09c` |
| Original XDC | `e1c892563932bfae60eddf7253e123a06239bce6c2c1ac3928186ba00921f10c` |
| nextpnr 52d3cc8 | `8b80c5f49fbb8d9433305d904ef707bd0f2cf4b18afb77f41fe9f5d511687cc9` |
| Matched chipdb | `d3d90cb680525dcf42b19dde35df9660ca7a9a48b5865bd33404129a2595b284` |
| Final timing JSON | `180cf9ce4bbce7b168e59facec89d948e731c00c09a6d3216e7a6e2fabbf7703` |
| Final nextpnr log | `048edfacc0d6d0de3da265c01df42286acb58cc48d34a5c2b8981f672fcdf2b2` |

Full synthesis/CSR proof used Yosys 0.63+173 (`66306a8ca-dirty`); boot proofs
used Homebrew Yosys 0.63. Route executable:
`/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx`, database:
`/tmp/tiny3tpu-nextpnr-current/kc705.bin`, seed 4, `--freq 100`, default HeAP.
Parent comparisons come from `build-ddr/synapse-current-baseline.log` and
`../interconnect/RESULTS.md`; neither was rerouted.

Reproduce with `python3 hardware/synapse32/experiments/combined/run.py` from
the repository root. This starts a new unique experiment and one new route;
do not rerun merely to inspect evidence. For read-only verification use
`python3 hardware/synapse32/experiments/combined/audit.py /tmp/tiny3tpu-combined-lhxjpxns`.
Three initial runner attempts failed during input-path parsing, before any
proof, synthesis, or route; their empty unique temporary directories remain.

## Requested parent CMake check

Read-only inspection confirms `synapse32_timing_report` uses
`${Python3_EXECUTABLE} -m unittest discover -s tests -p test_synapse32_timing_report.py`
with `WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}`. Running that command
with bytecode writes disabled from the source root passed all 11 tests.
The parent's separate all-26 regression was not duplicated or claimed here.
No CMake changes were made.
