# Track 3: Synapse32 interconnect experiment

Candidate: `synapse32_dram_soc.sv`, an isolated replacement for the production
SoC module. Integrate only its boot-address generate block after review; do not
replace unrelated parent changes with this snapshot. No main RTL, CMake, CPU
sibling source, firmware, DDR configuration, or constraints were edited.

## Change and contract

Replace the two boot-window inequalities with upper-address equality when
BOOT_WORDS is a power of two from 1 through 536870912. For the board's 16384
words this is exactly `req_addr[31:16] == 16'h8000`. Other parameter values use
the original expression. The upper bound prevents specializing a wrapping
window. The boot index, RAM read and byte-write processes, reset, response
registers, local/error priority, peripheral enables, and all transaction state
are unchanged. No cycle or protocol change is proposed.

Inspected the sequencer, local decode/RAM, Wishbone bridge, and board CSR/DRAM
decode. The sequencer must retain its enabled-edge/settle contract. Wishbone
must retain one outstanding request, held response, and ERR-over-ACK priority.
The external 1 GiB window and controller CSR window are unchanged.

## Equivalence evidence

`check.py` extracts each version's actual controller source. CPU/sequencer
requests, peripheral read data, and external responses become unconstrained
inputs. RAM read data is an arbitrary shared input; all RAM read/write enables,
address and write data are compared, as are peripheral side-effect enables.
This is a compositional controller proof, not a full CPU/DDR proof or an
array-content proof. Unchanged RAM logic plus identical read/write controls
and data preserve the actual array behavior from identical initial contents.

Yosys 0.63: `equiv_simple; equiv_induct -seq 4; equiv_status -assert` passed
for BOOT_WORDS 16384, 3, 32768, 1, 2, 536870912, 536870913, and 1073741824.
These cover the board configuration, non-power-of-two fallback, minimal and
maximum specialized decode, and fallback boundaries. Very large/minimal sizes
are decode/controller checks only, not claims that such physical RAMs build.
The proof includes invalid/idle output cycles, arbitrary stalls/responses,
resets, errors and byte strobes; no traffic assumptions or latency masking.

Source SHA256:

- Original: `48d7a8f4e55e86328be8b07deee03ecf4b69232955d39bb6995dfe62f9ef0ee8`
- Candidate: `bb4c897a22647dcac9f3254e34cc32e2ea57094b3b2d57a72df5c6fa29a07a52`

Logs and machine-readable counts:
`/tmp/tiny3tpu-interconnect.AjyWX5/bootdecode-expanded/`.

## Synthesis evidence

| Cells | Extracted original | Extracted candidate | Full baseline | Full candidate |
|---|---:|---:|---:|---:|
| LUT1..LUT6 | 115 | 105 | 23450 | 23383 |
| CARRY4 | 4 | 0 | 1998 | 1994 |
| Flip-flops | 134 | 134 | 12901 | 12901 |
| MUXF7 | 4 | 7 | 3524 | 3597 |
| MUXF8 | 0 | 1 | 1483 | 1480 |
| RAMB36E1 | abstracted | abstracted | 16 | 16 |

Full candidate uses `build-ddr/synth.ys` with only the SoC source path and
output JSON path substituted, the baseline Slang-enabled Yosys, and existing
DDR and firmware artifacts. Full synthesis used Yosys 0.63+173
(`66306a8ca-dirty`); isolated proofs/mapping used Homebrew Yosys 0.63
(`70a11c6bf0e8`). `check -assert` passed. DSPs, clock primitives,
DDR I/O primitives, and distributed RAM counts match. Global ABC remapping
changes other LUT/mux counts; the 67-LUT delta is not a localized guarantee.
The removal of the four boot-comparator carry cells is directly attributable.
Full synthesis output: `/tmp/tiny3tpu-interconnect.AjyWX5/full/`.
`compare_full.py` also passed exact top-port, boot RAM parameter/INIT, and
clock/DDR primitive parameter comparisons against `build-ddr/soc.json`.

The rejected parallel UART/TPU local-response mux rewrite passed controller
equivalence but increased extracted LUTs from 115 to 119. It was removed from
the candidate. Its extracted source and logs remain at
`/tmp/tiny3tpu-interconnect.AjyWX5/` for review.

## Baseline routing and fanout

Parent diagnostic baseline: `build-ddr/synapse-current-baseline.log`, nextpnr
52d3cc8, matched `/tmp/tiny3tpu-nextpnr-current/kc705.bin`, seed 4, original XDC.
No duplicate baseline route was run by this track.

Final baseline frequencies: `clk` 39.97 MHz and `soc.cpu_clk` 6.29 MHz,
both FAIL at 100 MHz; `clk200` 1324.50 MHz and `memory.iodelay_clk` 665.78 MHz.
The system critical path starts at `soc.sequencer.state[0]`, traverses the
request address and original boot comparator, and ends at the CE of
`soc.serial.rx_fifo[9]` (25.0 ns, 3.6 ns logic / 21.4 ns routing). Thus the
boot-decode optimization addresses an observed system critical path, though
the separate CPU path remains far from timing closure.

Mapped baseline input-pin fanout maxima: external_pending 38, req_addr 37,
local_boot 32, req_wdata 31, req_write 14, boot_address 6. These are netlist
counts, not routed capacitance. Boot address/index bits feed all 16 RAMB36s.

## Candidate route and recommendation

Exactly one candidate route completed with nextpnr 52d3cc8, matched chipdb,
seed 4, frequency 100, and the unchanged original XDC. No timing-allow-fail
or force option was used. The tool exited 0 despite reporting timing FAIL;
the result is explicitly treated as failed timing, not a usable board image.

| Final clock result | Parent baseline MHz | Candidate MHz |
|---|---:|---:|
| clk, target 100 | 39.97 FAIL | 44.47 FAIL |
| soc.cpu_clk, target 100 | 6.29 FAIL | 5.37 FAIL |
| clk200, target 200 | 1324.50 PASS | 1349.53 PASS |
| memory.iodelay_clk, target 200 | 665.78 PASS | 299.85 PASS |

System Fmax improves 11.3%, while CPU Fmax regresses 14.6%. The candidate
system critical path is 22.5 ns (3.4 ns logic / 19.1 ns routing), compared
with baseline 25.0 ns. These are single-seed, whole-design placement results;
do not attribute every changed route to the local decode or claim general
timing improvement. Logs: `full/route.log`, report `full/timing.json`, routed
netlist `full/soc_routed.json` under the experiment's /tmp directory.

Recommendation: retain this isolated, equivalence-proven candidate for parent
evaluation with CPU-track changes, but do not integrate unconditionally on
performance grounds. It saves decode hardware and improves the observed
system path while worsening the current overall CPU bottleneck. Parent owns
the integration decision and must evaluate combined timing with original
clocks and constraints. No further route was run by this track.

Both diagnostic flows retain the original DCI XDC. The router warns
`set_property: target get_iobanks not supported (on line 486)`; this is an
unresolved physical-constraint limitation. No DCI removal, timing exceptions,
false paths, ignored timing failures, FPGA programming, or physical-ready
claim is permitted by these results.

## Reproduction

Create a unique directory with `mktemp -d /tmp/tiny3tpu-interconnect.XXXXXX`.
Run `python3 hardware/synapse32/experiments/interconnect/check.py --out DIR`.
Run `prepare_full.py --out DIR/full` to prepare the full synthesis script,
then use the baseline Yosys with `-Q -T -m slang -s DIR/full/synth.ys`.
Set `OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2`. Routing is serial for this
track; use the supplied nextpnr/chipdb, seed 4, `--freq 100`, and the unchanged
`build-ddr/kc705.xdc`. Never add `--timing-allow-fail` or `--force`. Inspect
logs for timing FAIL and unsupported constraints even if the process exits 0.
