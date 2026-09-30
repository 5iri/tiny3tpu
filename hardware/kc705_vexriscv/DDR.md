# VexRiscv DDR3 bring-up

This build uses the KC705's 1 GiB, x64 single-rank DDR3 SODIMM. The single-clock
variant uses a 100 MHz controller/system clock and 400 MHz DDR clock (800 MT/s),
but has not passed the timing guard. The `--ddr-cdc` variant keeps CPU and TPU
at 100 MHz and uses an 83 1/3 MHz controller with a 333 1/3 MHz DDR clock
(666 2/3 MT/s). It passes the route guard, but **normal memory reads/writes
still fail**. Internal 0.75 V VREF fixes the observed MPR receive-pattern
corruption; this has not yet produced a working DDR memory image.
Firmware boots from RAM at `0x80000000`,
calibrates LiteDRAM through `0xf0000000`, and uses uncached DDR at
`0x40000000..0x7fffffff` for the memory test and signed GEMM operands/results.

## Registered burst adapter

`litedram_wishbone32_to512.sv` connects the existing registered 32-bit CPU bus
to a full-width 512-bit LiteDRAM Wishbone port. One CPU word occupies one of
16 word positions in a 64-byte burst. The adapter replicates write data and
enables only the selected bytes, so partial writes require no read/modify/write.
The word address is divided by 16 before reaching LiteDRAM. Read selection is
split across a register: 512 to 128 bits on the memory ACK, then 128 to 32 bits
on the CPU response. Only one transaction can be outstanding.

This avoids the narrow native-port converter's accumulation/flush logic.
LiteDRAM bank command FIFOs are two entries deep with buffered outputs.
The stock DDR PHY, calibration code and controller timing parameters are used.

`tools/kc705_litedram_gen.py` also factors the chooser's ready expression:
`cmd.valid = valids[grant]`, so under `grant == i`, bank i can use `valids[i]`
directly. This removes a shared cross-bank mux without altering command timing.
The transformation checks the exact upstream source hash and does not edit the
installed package. `tools/kc705_litedram_ready_proof.py` proves equivalence of
the actual generated eight-bank chooser before and after the change.

The four-phase command chooser also evaluates ACT/RAS permission locally for
each bank. The selected command's ready signal and all DDR timing counters stay
unchanged. `tools/kc705_litedram_command_proof.py` proves all 1,520 equivalence
checks for the generated eight-bank multiplexer with KC705 timings. Both
transformations reject an unexpected upstream source version.

The DDR SoC registers address-window selection before peripheral access and
registers each CPU master's ACK/ERR directly. TPU counters use the minimum
width for their fixed bounds; cycle-by-cycle comparison against the original
integer counters covers N=2, 4 and 8, including asynchronous resets. These
changes preserve the accelerator's multiply/accumulate cycle count.

## Separate CPU and DDR clocks

`req_resp_cdc.sv` carries one request at a time between the 100 MHz CPU and
83 1/3 MHz memory domains. It holds each payload while a two-flop synchronized
toggle crosses the boundary. Responses use the same handshake in reverse.
Reset is coordinated across both domains and cancels any outstanding request.
One PLL produces both clocks: 200 MHz input, 1 GHz VCO, divide-by-10 CPU,
divide-by-12 controller and divide-by-3 DDR clocks. The UART divisor uses the
CPU frequency; LiteDRAM's configuration frequency remains the controller rate.

The CDC unit test passes 600 stalled transfers and 60 in-flight resets. Real
VexRiscv simulation at independent 100/83 1/3 MHz clocks passes 9,294 reads,
8,400 writes and 35 signed GEMM outputs in 3,773,730 CPU cycles. The controller
equivalence proof also passes with the 83 1/3 MHz timing parameters.

`build-vexriscv/ddr-cdc/route.log` reports 107.98 MHz for the 100 MHz CPU/TPU
domain and 93.41 MHz for the 83.33 MHz controller domain. The two 200 MHz
domains also pass. The bitstream frame roundtrip passes, including external
VREF and all non-ECC bits; all 32 DSP PREG profiles are modeled.

On hardware, the image boots and write leveling detects transitions. Read
training finds no valid window, and the memory test fails. A firmware-only
diagnostic proves readback of all 512 DFI write-data CSR bits, but DDR3 MPR
reads mostly return idle data with the stock read latency. At a diagnostic
latency of seven controller cycles, a complete read-phase/bitslip/input-delay
sweep receives the fixed MPR pattern on lanes 4–7, while lanes 0–3 miss at
least one of eight samples. Sweeping all 32 command-clock delays does not
remove that error. These are prime-DQ MPR checks, not normal memory tests.
These results used the external-reference configuration. A subsequent
controlled comparison on the same routed PHY at 400 MHz DDR found:

| Input configuration | Fixed MPR window, 1,024 prime-DQ samples |
| --- | --- |
| External VREF, default input power | 246 errors |
| External VREF, high-performance input buffers | 256 errors |
| Internal nominal 0.75 V VREF | **0 errors, all eight lanes** |

The history scan searches all 32 input delays, all 32 command delays, all four
command phases and every eight-sample position in eight recorded DFI cycles.
The repeated check freezes the selected window; it does not rescan on every
read. MPR checks only prime DQ on each x8 chip and cannot establish arbitrary
data ordering or that normal writes work. The internal-reference result also
does not establish whether the external-reference failure originates in board
hardware or FPGA configuration.

The 100 MHz CPU/TPU, 83 1/3 MHz controller, seven-cycle read-latency image also
passes all eight prime-DQ MPR checks with internal 0.75 V. Stock normal-memory
training fails with both seven- and eight-cycle read latency. A diagnostic
that freezes the passing MPR read settings and then searches write phase,
bitslip and output delay still fails arbitrary-data readback: 14,850 errors
in 32,768 checked bits. No DDR-backed GEMM or DDR stress pass has occurred.
Evidence: `build-vexriscv/ddr-phy400-{history,rxfast,internal075}/` and
`build-vexriscv/ddr-cdc-retrain-rd7/`.
The diagnostic `--ddr-read-latency-offset` option changes both
the PHY valid pulse and the controller's expected read latency; it is not a
validated fix. No hardware DDR-backed GEMM pass has been observed.

`--ddr-trace` (with `--ddr-cdc --ddr-debug`) adds a sixteen-cycle read history
triggered by a DFI read enable. Each recorded byte holds one lane's eight
prime-DQ samples in chronological, least-significant-bit-first order; a
separate mask records DFI read-valid. The recorder is passive and freezes
until rearmed. Its simulation checks ordered capture, valid alignment,
freeze and rearm:

```sh
.venv-ddr-compat/bin/python tests/test_kc705_phy_read_trace.py
```

The optional `--ddr-stress` firmware tests 2 MiB across eight windows spanning
the DIMM, with two pattern/inverse rounds and every byte position in a burst.
Its host check passes and rejects injected address aliasing. It has not yet
run successfully on the physical DIMM.

## I/O profiles

The default `--ddr-io dci` retains the stock `SSTL15_T_DCI` DQ standard and
`DCI_CASCADE {32 34}` on bank 33. The current open-source database/backend lacks
DCI support; ignoring that constraint is still a build failure.

The explicit `--ddr-io experimental-sstl15` profile uses plain SSTL15 on DQ,
matching [OpenXC7's KC705 DDR demo](https://github.com/openXC7/demo-projects/blob/7cfd51ed5e881721d54954c6ae5966535912117f/litex-ddr-kc705/xilinx_kc705.xdc).
It has **no FPGA DCI input termination** and no DCI cascade. DDR voltage,
pin assignments, differential strobes, and DRAM-side ODT remain unchanged.
This is an alternative electrical experiment, not an implementation of DCI.
Passing board tests is bring-up evidence, not signal-integrity/PVT signoff.
`io-profile.json` records the selected profile and is bound into the bitstream
manifest. No tool silently substitutes this profile for DCI.

KC705 banks 32 and 34 use the board's external 0.75 V VREF. This nextpnr
backend incorrectly emits an internal 0.675 V VREF feature for SSTL inputs.
`kc705_fix_external_vref.py` removes exactly those two features, retains the
raw FASM, and records their hashes. It rejects unexpected features or banks.
The exporter verifies that internal VREF is disabled in external-reference images.
Its frame roundtrip excludes only generated ECC bits 12:0 of word 50, retaining
checks on the configuration bits above them. See
[AMD UG810](https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content)
for the board's VREF connection.

For the explicit internal-reference diagnostic, run
`tools/kc705_set_internal_vref.py` **instead of** the external-reference
correction, before export. It replaces only the two implicit 0.675 V features
with nominal 0.75 V, retains the original FASM and records all hashes in
`internal-vref.json`. The I/O profile explicitly records the reference source
and voltage. The exporter checks the exact two features and their physical
frame bits; it rejects an unrecorded internal reference or another voltage.
This is the setting that passes the MPR receive check on this board, but it
is still diagnostic. [UG471, Internal VREF](https://docs.amd.com/api/khub/documents/IbGcnPFe6eF19RHma_Y~IA/content)
documents the nominal internal reference option for SSTL15.

`tools/kc705_set_ddr_rx_performance.py` is a separate, unsuccessful diagnostic.
It changes exactly the 64 DQ input-buffer low-power bits, with pad locations
derived from the routed netlist and checked against the package pin table.
The exporter checks all 64 physical bits and preserves every other feature.
It did not fix the external-reference failure and is not a default setting.

`--ddr-phy-only --ddr-debug --ddr-trace --ddr-cdc` removes the native memory
controller for isolated PHY tests. Its firmware deliberately disables native
memory testing and cannot report a DDR-backed GEMM pass. The timing-passing
400 MHz PHY diagnostic uses `--ddr-controller-mhz 100 --diagnostic-cpu-mhz 50`;
the slow CPU is diagnostic only. Firmware macros `TINY3TPU_DDR_HISTORY_SCAN`,
`TINY3TPU_DDR_PAD_LOOPBACK` and `TINY3TPU_DDR_PAD_PATTERN=0x17` select the
recorded-wave and pin-loopback tests. The latter keeps DRAM CS inactive while
the FPGA drives its own pads. `TINY3TPU_DDR_RETRAIN` selects experimental
MPR-first write training; a successful training result still must pass the
normal native memory test and GEMM before firmware reports success.

## Reproduce

```sh
.venv-ddr-compat/bin/python tools/kc705_litedram_ready_proof.py \
  --out build-vexriscv/ddr-ready-proof
.venv-ddr-compat/bin/python tools/kc705_litedram_command_proof.py \
  --sys-clk-freq 83333333.33333333 --out build-vexriscv/ddr-command-proof-new
python3 tools/kc705_vexriscv_sim.py cdc --synapse32-dir ../synapse32 \
  --out build-vexriscv/ddr-cdc-cpu-test-new
.venv-ddr-compat/bin/python tools/kc705_open_build.py route \
  --cpu vexriscv-lite --synapse32-dir ../synapse32 \
  --ddr-io experimental-sstl15 --ddr-cdc --build-dir build-vexriscv/ddr-cdc-new \
  --chipdb /tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin
# Export only after the route passes the clock/constraint guard.
python3 tools/kc705_fix_external_vref.py --build-dir build-vexriscv/ddr-cdc-new \
  --db-root build-vexriscv/prjxray-db/kintex7
python3 tools/kc705_export_bitstream.py --build-dir build-vexriscv/ddr-cdc-new \
  --db-root build-vexriscv/prjxray-db/kintex7
uv run --with pyserial python tools/kc705_program_capture.py \
  --build-dir build-vexriscv/ddr-cdc-new --label first
```

Programming targets volatile FPGA SRAM; it does not write configuration flash.
The capture tool opens UART before programming and saves the initial calibration
log, the final result, the programming log, and the bitstream hash.

## Validation so far

- The adapter passed 3,587 directed/random accesses, including all 16 word
  positions and all 16 byte masks, 0–20 cycle stalls, errors and reset.
- Real VexRiscv through both production adapters passed 9,294 reads, 8,400 writes
  and all 35 independently checked signed GEMM results against a 512-bit memory
  model with 1–23 cycle response delays. This does not simulate the DDR PHY.
- The generated command-chooser proof passed all 76 equivalence checks.
- The complete four-phase command multiplexer passed all 1,520 equivalence
  checks after factoring ACT/RAS permission into each bank's ready path.
- The first full-width route reached 89.50 MHz. Subsequent interconnect and
  controller changes reached 98.76 MHz (seed 2), still failing the 100 MHz
  target. Those failing routes were not programmed.

Physical calibration and memory results must be recorded separately before
calling a DDR image working. See `BRINGUP.md` for the last verified board image.
