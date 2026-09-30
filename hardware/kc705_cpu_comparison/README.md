# KC705 replacement-CPU comparison

2026-09-26: **VexRiscv Lite is the recommended replacement candidate** for the
TPU control CPU. Fresh isolated routes pass the native 100 MHz check for both
tested VexRiscv variants. The current TPU peripheral, tested separately,
still fails that check. Replacing the CPU alone does not close the complete SoC.

| Isolated probe | Final native Fmax | 100 MHz target | LUTs | FFs | DSPs | BRAM cells |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| VexRiscv Minimal | 122.74 MHz | PASS | 1,021 | 994 | 0 | 2 |
| VexRiscv Lite | 128.34 MHz | PASS | 1,774 | 1,226 | 0 | 4 |
| Existing TPU + AXIS transport + mailbox | 89.33 MHz | FAIL | 3,170 | 4,391 | 32 | 0 |

Cell counts include the diagnostic shell. BRAM counts combine RAMB18E1 and
RAMB36E1 cells and are not normalized to memory capacity. This is one seed per
configuration; a faster Lite result in this run does not establish that Lite
always times better than Minimal.

## CPU choice

[VexRiscv](https://github.com/SpinalHDL/VexRiscv) provides a pipelined RISC-V
CPU and an existing [LiteX Wishbone integration](https://github.com/enjoy-digital/litex/blob/master/litex/soc/cores/cpu/vexriscv/core.py).
The tested Lite variant includes RV32IM arithmetic with iterative multiply/divide,
a 2 KiB instruction cache, and a simple data bus. The Minimal variant is RV32I.
Both expose instruction and data Wishbone masters with acknowledgement/error
inputs, allowing memory stalls without the Synapse32-specific CPU clock gate.
Sources are generated Verilog, so using these fixed variants does not require
a local Scala/SpinalHDL generation toolchain.

The proposed integration is VexRiscv Lite -> Wishbone interconnect -> boot RAM,
UART, LiteDRAM, and a Wishbone adapter for the existing TPU mailbox. Preserve
the TPU packet protocol and MMIO map where practical; replace the CPU-specific
sequencer and clock-enable integration. Use a registered bus boundary to avoid
recreating a long combinational peripheral decode/response path. Firmware and
bus handshakes still need end-to-end testing after that integration.

PicoRV32 is a smaller-interface alternative with native valid/ready, Wishbone,
and AXI variants. Its upstream documentation describes an approximately four
cycle average CPI under the stated memory assumptions and a custom interrupt
scheme. VexRiscv is the stronger fit here for the existing LiteX/LiteDRAM stack
and a more capable control processor. No PicoRV32 timing run was performed.
Reference: [PicoRV32 documentation](https://github.com/YosysHQ/picorv32).

## TPU finding

The default PE in `systolic_array/rtl/pe.v` retains asynchronous reset on its
accumulator. Fresh synthesis maps all 32 TPU DSP48E1 cells with
`AREG=BREG=MREG=PREG=0`. The final critical path runs from a neighboring PE's
A forwarding register through the multiplier to an accumulator fabric FF:
**11.2 ns**, including 5.8 ns modeled logic and 5.4 ns routing.

DSP48E1 register resets are synchronous; asynchronous datapath reset can
prevent absorption into DSP registers. See
[AMD DSP48E1 primitive documentation](https://docs.amd.com/r/2021.1-English/ug953-vivado-7series-libraries/DSP48E1).
The existing [PE reset-ownership experiment](../synapse32/experiments/pe-valid/README.md)
is a relevant candidate: it preserves the visible reset behavior while allowing
the accumulator into PREG, without adding MAC cycles. Its historic validation
was not rerun here. The installed backend's incomplete registered-DSP coverage
means a higher native Fmax after enabling PREG would not alone prove closure.

## Method and limits

`run.py` generates a board-pin-compatible scan shell with registered core inputs
and sampled/shifted outputs so the selected logic remains observable. It uses
a real 200 MHz input -> PLL -> 100 MHz BUFG clock and explicitly constrains the
internal clock nets. Interrupt inputs are tied inactive on the CPU probes.
The shell is not a working SoC or a firmware execution test and is not programmed.
CPU reset distribution is the critical path in the Lite probe.

All runs use Yosys `0.63+173 / 66306a8ca-dirty`, installed nextpnr `68aeeb3`,
heap/router2 seed 4, and the same KC705 database as the preceding investigation:
`/tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin`.
Synthesis structural checks pass for all three probes. Final route reports,
routed JSON, exact commands and source hashes are in
`build-cpu-comparison/{vex-min,vex-lite,tpu}/`.

These are comparative native timing diagnostics, not validated whole-chip
Fmax. The backend's primitive, clock, reset, hold and external-I/O coverage
limitations remain. Combined placement, interconnect and DDR add paths and
congestion absent from these probes. The earlier VexRiscv DDR reference in
`hardware/kc705_ddr_reference/README.md` also missed its whole-system target.

## Reproduction

The dependency is pinned to the
[LiteX VexRiscv data repository](https://github.com/litex-hub/pythondata-cpu-vexriscv)
commit `642ecfed1c84460555d6d803d660cc60cfc1ecb6`.
Its generated HDL identifies VexRiscv source revision
`8542a5786b26857f3ef830ae9e72eec031df42d3`.

```sh
git clone https://github.com/litex-hub/pythondata-cpu-vexriscv.git build-cpu-comparison/upstream
git -C build-cpu-comparison/upstream checkout 642ecfed1c84460555d6d803d660cc60cfc1ecb6
python3 hardware/kc705_cpu_comparison/run.py vex-min
python3 hardware/kc705_cpu_comparison/run.py vex-lite
python3 hardware/kc705_cpu_comparison/run.py tpu
```

The script requires the no-DDR XDC generated in
`build-clock-diagnosis/noddr/kc705.xdc` by the preceding diagnostic build.
It now returns status 2 when a completed route reports `FAIL at`, after saving
the result. Initial measurements were made before adding that exit-status
guard; their manifests already mark the TPU result rejected.

No production CPU, TPU RTL, firmware, or board defaults have been changed.
