# Registered DMA descriptor ends

The retained near-100 MHz route has an expanded path through DMA TX address
addition, span comparison, and START control. `synapse32_axi_dma.sv` now keeps
33-bit TX/RX span ends current on each accepted descriptor write. START still
sees the result on the next cycle, even when that field was the last write;
the register ABI and DMA issue cycle are unchanged. This separates the
addition from the overlap and range decisions.

The open DMA unit test passes **33 cases**, including each field written
immediately before START for both accepted and rejected descriptors. The
RV32IM CPU+DDR+TPU system test passes at
**153,886 instructions / 198,945 CPU edges = 0.773510 IPC** and **1,050,890
system cycles**. The five-shape stress test passes at **240,440 instructions /
321,416 CPU edges = 0.748065 IPC** and **1,723,990 system cycles**. An
isolated baseline run used a copy of the original DMA wrapper whose SHA-256
exactly matches the historical synthesis manifest. With the same firmware
and CPU overlay, the baseline has **identical** instruction counts, CPU
edges, system cycles, DMA beat/burst counts, and memory-model metrics for
both workloads. This change adds no observed cycles and preserves measured
IPC for those workloads. The baseline driver is
`tools/synapse32_dma_matched_baseline.py`; outputs are in
`build-dma-descriptor-end-register-baseline-system` and
`build-dma-descriptor-end-register-baseline-stress`.

For an isolated open-source route comparison, Yosys used the exact older
`build-ddr-uart-prefix` synthesis inputs except for the DMA wrapper. The
historical clock-enable source was recovered from
`build-clock-enable-low-phase-test/original.sv`; its SHA-256 matches the
historical synthesis manifest. With the same nextpnr backend, KC705 XDC,
chip database, frequency target, and seed 5, the old netlist routes at
**91.70 MHz system / 105.53 MHz CPU** and the changed netlist at **92.73 MHz
system / 105.57 MHz CPU**. The changed synthesis adds 66 fabric flip-flops
and 58 LUTs, with 36 DSPs in both designs. Reports are in
`build-dma-descriptor-end-register-baseline-route` and
`build-dma-descriptor-end-register-route`.

This is a **1.03 MHz native system timing gain** on the matched older
source, not a physical 100 MHz result. The retained optimized route was
not regenerated from the changed RTL; its expanded 10.155 ns modeled
maximum and the wider coverage gaps remain open. The next useful check is
to carry this DMA change into the retained source and re-run the full
physical and workload checks.

Integration cannot be inferred by reusing the existing near-100 MHz route.
The changed wrapper's fresh Yosys netlist has **35,480** cells, compared
with **35,302** in the older `build-ddr-uart-prefix` synthesis; it adds
**66 FFs** and **58 LUTs**. Only **9,257** cell names occur in both files,
and just **55** of those have the same type and connections. In contrast,
the old UART netlist and the later packed-logic optimization input share
**35,294** exact cell instances. Thus the registered-end RTL is in the
tested source and older matched route, but not in the saved near-100 MHz
packed netlist. A new full synthesis plus functional/workload and routed
timing checks is required before attributing any near-100 MHz result to it.

A route of that fresh synthesis with the grade-2 nextpnr backend, KC705
constraints, 100 MHz request, and seed 5 completed in
`build-dma-descriptor-end-register-grade2-route`. Its `routed.json` is
**byte-identical** to the previous changed-source route (SHA-256
`11df3eb08c783568c8ec274223c944e753841e1eb32ea83513161434b987df68`),
and reports the same **92.73 MHz system / 105.57 MHz CPU** native timing.
The newer placer backend alone therefore does not carry the source-level
DMA improvement into the later packed near-100 MHz implementation.

To locate reusable placement guidance, `tools/synapse32_match_dma_synth_cells.py`
matches primitive structure against shared named nets and propagates unique
matches. An identical-netlist self-check found **35,107 / 35,302** cells;
the old/new DMA synthesis comparison found **25,503** candidate matches.
Source-attributed coverage is **2,390 / 2,420 CPU**, **6,776 / 6,845 DDR**,
and **11,515 / 11,656 TPU** cells, but **0 / 212 old DMA wrapper** cells.
These are candidate identities for placement guidance, not an equivalence
proof. The report is `build-dma-descriptor-end-register-structural-match.json`.

The grade-2 checkpoint exporter produced a fresh packed, placed, and routed
new-DMA build at `build-dma-descriptor-end-register-grade2-checkpoint`.
With the historical guidance settings (carry 100 ps, primitive/domain
guidance, placement beta 0.4), its native estimate is **86.21 MHz system /
93.17 MHz CPU**, a regression from the saved near-100 MHz route. Of the
candidate matches, **24,937** cell names occur in both packed designs and
**24,935** retain a packed primitive type, but only **6,188** also retain
the same BEL class (such as `C6LUT` versus `C5LUT`). Directly fixing old
BELs in the new checkpoint is therefore unsafe without a checked
placement adaptation and new timing/functional validation.

A matched seed sweep of the fresh registered-DMA synthesis with the same
KC705 XDC and grade-2 nextpnr backend gave native system/CPU estimates:
seed 4 **86.78/109.17 MHz**, seed 5 **92.73/105.57 MHz**, seed 8
**94.06/104.37 MHz**, and seed 12 **79.84/96.76 MHz**. Seed 16 failed
nextpnr's post-placement validity check and has no timing result.
Seed 8's timing-graph export reproduced its routed JSON byte for byte
(SHA-256 `fc36cf5ba2cb3456f8032acc5bfcf4bbbf62e36eeda0a070e4e7e2d2610a743b`).
`tools/synapse32_analyze_fresh_route.py` expands its mapped FF/control
timing: **607** `clk`→`clk` endpoints exceed 10 ns, with a **12.467 ns**
LiteDRAM write-address/control path; the CPU-domain maximum is
**10.555 ns**. This shows that seed 8's native improvement is insufficient
and that the earlier packed DDR/CPU optimizations must be reproduced or
replaced on the new source. The expanded analysis still lacks qualified
Kintex DSP, generic carry/clock/hold, and DDR IO signoff.

The structural matcher tentatively associates the fresh seed-8 worst DDR endpoint
`$auto$ff.cc:337:slice$66871` with old endpoint
`$auto$ff.cc:337:slice$66898`. In the retained optimized route that old
endpoint measures **9.925 ns** in the expanded graph; in the fresh route
the candidate endpoint measures **12.467 ns**. The launch registers
and intervening LUT/mux topology differ, so copying a single BEL or the
old endpoint route is not sufficient to recover the optimized behavior.

An isolated generated-LiteDRAM trial replaced the five parallel
`main_write_w_buffer_level2` bit updates with precomputed increment and
decrement candidates selected by queue/dequeue. All **128** local
state/control cases matched the original transition and full SoC synthesis
completed. The seed-8 route regressed sharply: native system Fmax
**94.06 → 69.42 MHz**, expanded system maximum **12.467 → 14.575 ns**, and
over-10 ns system endpoint count **607 → 1,543**. It is rejected and is not
in the retained RTL. See `build-dma-ddr-level2-select-rtl`, `...-synth`,
`...-seed-8`, and `...-seed-8-expanded`.
