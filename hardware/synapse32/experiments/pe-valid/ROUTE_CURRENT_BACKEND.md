# KC705 PE output-register route trials

The PE reset-ownership variant remains isolated. Its formal proof, mapped
primitive test, and 45-shape GEMM workload check are recorded in [README.md](README.md).
No CPU ISA or firmware change was made for these route trials.

With the current nextpnr backend, a matched older SoC synthesis comparison at
heap seed 5 moved all 32 PE accumulators into DSP PREG and removed 1,023 fabric
flip-flops. Native system Fmax improved **82.14 → 87.05 MHz** and CPU Fmax
**99.26 → 101.01 MHz**. The exact reports are in
`build-pe-valid-matched-baseline/comparison.json`.

The same PE source on the later `build-ddr-uart-prefix` synthesis base mapped
the same 32 PREGs and removed the same 1,023 flip-flops. Its matched heap
seed-5 route **regressed**: system **91.70 → 84.09 MHz**, CPU
**105.53 → 97.66 MHz**. Candidate-only seeds 4 and 8 reached system
83.43 and 87.57 MHz. This variant is not selected. Reports are in
`build-pe-valid-uart-prefix-synth/comparison.json` and the seed directories.

Those Fmax numbers omit registered DSP timing. The older strict timing model
incorrectly rejected PE DSP controls because nextpnr replaces tied-low pins
with tied-high plus inversion. `model-inversions.inc` corrects that check, and
`tools/synapse32_verify_packed_dsp_controls.py` verifies the effective mode of
all 32 packed PE DSPs against synthesis. Strict analysis now stops on four
CPU DSPs with a different A/B/M-register profile. No physical 100 MHz claim
is made from these trials.

The retained routed design is still
`build-grade2-incremental-cq-tpu-output-pairs`: native system **100.14 MHz**,
CPU **100.53 MHz**, but the expanded mapped FF/control probe reaches
**10.185 ns**, so physical closure is unproved. A one-register move of PE
input FF `$auto$ff.cc:337:slice$105095` to `SLICE_X90Y155/C5FF` preserved
the functional cells and locked routes and reduced that PE endpoint to
9.990 ns. Another DDR/control endpoint rose to **10.278 ns**; the move is
rejected. See `build-grade2-incremental-cq-tpu-input-ff-near-dsp-v4` and
`...-v4-mapped`.

A second placement of the same FF at `SLICE_X90Y154/C5FF` routed with exact
logical cells and retained nets but dropped native system Fmax to **86.84 MHz**.
The south placement at `SLICE_X89Y154/C5FF` failed nextpnr's post-placement
validity check. Neither is selected.

An output-only reroute of CPU divider LUT
`$abc$216920$auto$blifparse.cc:557:parse_blif$218479` to
`SLICE_X104Y47/C6LUT` preserves the mapped logic and all retained routes.
Native system Fmax stays **100.14 MHz** and CPU Fmax rises **100.53 →
106.36 MHz**. The expanded CPU path falls **10.117 → 9.875 ns**, while the
expanded system path remains **10.185 ns**. This is a diagnostic timing
improvement, not physical signoff; see
`build-grade2-incremental-cq-cpu-divider-lut-output-only` and `...-mapped`.

Combining that CPU move with the PE input FF move above, starting from a
reconstructed pre-route netlist with all previously routed nets carried
forward, also preserves mapped logic, placements, and retained routes.
Native Fmax is **100.14 MHz** system and **106.36 MHz** CPU. Expanded paths
are **10.156 ns** system and **9.875 ns** CPU. The new worst system endpoint
is PE FF `$auto$ff.cc:337:slice$104808`; the path still exceeds the 10 ns
target. See `build-grade2-incremental-cq-cpu-divider-hydrated-plus-tpu-input-ff`
and `...-mapped`. Relocating the previously critical TPU output LUT/FF pair
to `SLICE_X90Y150` with the CPU move leaves the expanded system path at
**10.185 ns** and is not selected.

A same-slice `C6LUT/CFF` to `D6LUT/DFF` move for the new worst endpoint
routed with identical functional cells and monotonic preservation of all
preexisting non-ground route segments. It did not change the expanded
**10.156 ns** path and is not selected. The adjacent-site moves tried here
were rejected by nextpnr before timing could be evaluated.

Tracing the 10.156 ns path identifies a PE input FF → DSP multiply →
accumulator LUT/FF path. Moving its launch LUT/FF from the B slot to the D
slot in `SLICE_X89Y147` preserves mapped logic and all preexisting
non-ground route segments, and gives native **100.21 MHz** system and
**106.36 MHz** CPU. The expanded system maximum only falls to **10.155 ns**;
the worst endpoint switches to a DMA address/descriptor-valid path. The C
slot trial reduces native system Fmax to **98.57 MHz** and is rejected. See
`build-grade2-incremental-cq-cpu-divider-pe-input-source-pair-dslot` and
`...-mapped`. The D-slot route is diagnostic, not physical signoff.

The expanded graph for that D-slot route has **55 `clk`→`clk` setup
endpoints above 10 ns**: 29 attributed to PE accumulator RTL, 15 to the
LiteDRAM gateware, 7 to TPU DMA batch framing, 2 to the AXI DMA control
wrapper, 1 to the CPU execution unit, and 1 to AXI DMA write logic. The
maximum path is now **10.155 ns** through DMA address arithmetic and descriptor
validation. These counts are modeled endpoints, not a complete physical
timing signoff. They show that isolated BEL moves cannot by themselves close
all known 100 MHz violations.

The DMA address/descriptor chain has a separate RTL-stage optimization and
matched older-source route result in
`hardware/synapse32/experiments/dma/DESCRIPTOR_END_TIMING.md`. It improves
native system Fmax on that source from **91.70 to 92.73 MHz** without a CPU
Fmax regression, but has not yet been integrated into this retained route.

A mode-specific DSP delay **sensitivity check** on the accepted CPU+PE
placement route substitutes the local Artix-7 SDF's 3.841 ns A→P maximum
for the backend's pooled 5.40 ns on the 32 exact-mode PE DSPs. It changes
46,080 graph arcs and leaves **26 `clk`→`clk` endpoints above 10 ns**:
15 LiteDRAM, 7 DMA batch framing, 2 DMA wrapper, 1 AXI DMA write, and 1
CPU. The worst remains **10.155 ns**. Nine DMA endpoints share the TX
descriptor-end arithmetic chain, while nine of the LiteDRAM endpoints
are launched by `memory.main_write_beat_offset[2]` through address carry
logic. This is only a prioritization probe: the Artix-7 SDF is not a
KC705 Kintex-7 timing qualification. The graph and analysis are in
`build-grade2-incremental-cq-cpu-divider-hydrated-plus-tpu-input-ff-mapped/`.

Moving the LiteDRAM offset register and its LUT to `SLICE_X118Y71` preserved
the logical cells and all preexisting non-ground route segments, but made
the expanded worst path **10.388 ns**, so it is rejected. Two closer free
sites at `SLICE_X113Y75` and one at `SLICE_X113Y74` failed nextpnr's
post-placement validity check before timing; no timing claim is made for
them.

The next DDR-control experiments use the accepted CPU+PE placement route
without changing architectural state or latency. Moving the final reset
LUT to `SLICE_X128Y12/B6LUT` reduced the bank-register SR path
**10.136 → 9.666 ns** and improved its four other sinks. It passed a
monotonic audit of all preexisting non-ground route segments; the strict
route comparison still flags expected additions from the intermediate
CPU+PE input. `build-grade2-cpu-pe-ddr-reset-lut-y12` is the route.

Two further local copies of existing LUT functions split large DDR fanouts.
The first copies `$228612` to `SLICE_X113Y78/B6LUT` for 14 nearby sinks;
eight write-offset endpoints fall from as high as **10.118 to 9.338 ns**.
The second copies `$229060` to `SLICE_X141Y65/B6LUT` for seven low-bank
sinks; two endpoints fall from **10.057/10.004 ns** to **9.008/<9 ns**.
Both copies have identical LUT parameters and input connections to their
sources, and undoing the fanout split recovers every original functional
cell. Both routes pass exact placement, post-route functional-cell, and
monotonic retained-route checks, with native system/CPU estimates still
**100.14/106.36 MHz**. See
`build-grade2-cpu-pe-ddr-write-control-replica` and
`build-grade2-cpu-pe-ddr-bank-status-replica`.

Moving one unchanged DDR capture LUT/FF pair to `SLICE_X119Y40` then reduces
its data path **10.080 → 9.105 ns**, with the same native Fmax and a passing
functional/monotonic-route audit. See
`build-grade2-cpu-pe-ddr-capture-pair-x119y40`. Under the **unqualified**
Artix-7 DSP-mode sensitivity, the count of over-10 ns system endpoints
falls from **26 to 13** across this sequence. A further unchanged DDR reset
LUT move to `SLICE_X126Y12/C6LUT` reduces its SR path **10.027 → 9.925 ns**
and the count to **12**: nine share the DMA descriptor chain, two are
LiteDRAM, and one is CPU control. Its route is
`build-grade2-cpu-pe-ddr-reset2-lut-x126y12`; the mapped monotonic-route
audit passes despite the expected strict comparison failure on intermediate
source-route additions. The maximum remains
**10.155 ns**. This is measured progress on the diagnostic graph, not
physical 100 MHz closure; Kintex DSP timing, full primitive/IO coverage,
clock skew/hold and board behavior are still open.

With the original pooled DSP timing unchanged, over-10 ns system endpoint
count falls from **58 to 45** between the accepted CPU+PE route and the
capture-placement candidate. The original PE maximum remains **10.156 ns**.
Moving the unchanged launch LUT/FF pair of one PE path from the B to D slot
of `SLICE_X89Y147` on top of the second DDR reset placement reduces the
mapped over-10 ns endpoint count **44 → 41** and the maximum **10.156 →
10.155 ns**. Native system/CPU estimates are **100.21/106.36 MHz**; exact
placements and functional cells, plus monotonic retention of all preexisting
non-ground route segments, pass the independent audit. See
`build-grade2-cpu-pe-ddr-pein-dslot` and `...-mapped`. The mode-specific DSP
sensitivity still has 12 endpoints above 10 ns, so this is not physical
closure. The replica
and capture-placement steps change no state bits or pipeline cycles; no
new full-SoC workload simulation has been run for their packed-netlist
compositions.

Further placement-only probes from that PE D-slot input were rejected.
Moving the capture OR LUT to `SLICE_X116Y33/C6LUT` or
`SLICE_X114Y32/D6LUT` increased the LiteDRAM capture path from **10.038 ns**
to **10.125 ns** or **10.122 ns** respectively. Moving the last CPU reset
LUT to `SLICE_X95Y32/D6LUT` increased the mapped maximum from **10.155 ns**
to **10.162 ns**. These trials preserve functional cells and native Fmax,
but do not improve expanded timing. The local Project X-Ray database has
Artix-7, Spartan-7, and Zynq-7 DSP SDFs, but no Kintex-7 DSP SDF; none of
the alternate-family arcs can establish a KC705 100 MHz timing bound.

An experimental bitstream for the capture-placement DDR candidate is at
`build-grade2-cpu-pe-ddr-capture-pair-x119y40-bit/latest.bit`. The FASM
export rerouted from the pre-route JSON and reproduced the selected routed
JSON **byte for byte**. The recovered KC705 frame database converted it to
an 11,443,766-byte `.bit`; OpenXC7 readback reproduced every non-ECC input
frame word. `tools/synapse32_validate_ddr_candidate_bitstream.py` records
the source hashes and roundtrip in the bitstream manifest. The board was
not attached (`openFPGALoader --scan-usb` found no USB device), and this
image does **not** contain the separate source-level DMA end-register change.
It is not a physically closed 100 MHz or hardware-tested image.
