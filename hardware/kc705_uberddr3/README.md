# KC705 UberDDR3 hardware-only trial

This isolated target evaluates UberDDR3 as an alternative to the LiteDRAM
DDR3-only stage. It uses the KC705 oscillator, reset button, DDR3 pins and eight
LEDs. Calibration and memory tests run in hardware. There is no CPU, firmware,
UART, TPU, DMA or Ethernet.

All build and verification tools are open source: Python, Yosys/ABC, nextpnr-xilinx
and Icarus Verilog. No Vivado, ISE, generated MIG core or proprietary simulator
is required or invoked.

## Configuration

- XC7K325T-FFG900-2, MT8JTF12864 1 GiB single-rank x64 SODIMM.
- Clocks from the 200 MHz input using PLLE2_ADV: the 100 MHz controller profile
  uses an 800 MHz VCO, 400 MHz DDR clock (800 MT/s), 200 MHz delay reference and
  100 MHz system clock. The 83.333 MHz profile uses a 1 GHz VCO, 333.333 MHz DDR
  clock (666.667 MT/s), 200 MHz delay reference and a separate 100 MHz system
  clock.
- 14 row, 10 column, 3 bank address bits; eight byte lanes; 512-bit burst port.
- 1 Gb component refresh timing; conservative tRCD/tRP = 15 ns, tRAS = 37.5 ns.
- Kintex-7 ODELAY enabled; ECC, second Wishbone port and self-refresh disabled.
- Upstream BIST mode 1, including all 64 byte enables. External request inputs
  are idle; the controller performs its own initialization, training and BIST.
- Explicit `experimental-sstl15` I/O profile: FPGA DQ DCI termination is absent.
  The current openXC7 backend cannot implement the stock KC705 DCI constraints.
  DRAM output impedance is 34 ohms and nominal ODT is 60 ohms.

The snapshot and source transformations are documented in
[third_party/uberddr3](../../third_party/uberddr3/README.md). The build hashes its
inputs and generated controller in `hardware-manifest.json`.

## Build and verify

The existing `.venv-ddr-compat` environment supplies LiteX's official KC705 pin
definitions. LiteDRAM is not instantiated by this target.

```sh
python3 tests/test_kc705_uberddr3.py --pipeline-bist
.venv-ddr-compat/bin/python tools/kc705_uberddr3_build.py route \
  --ddr-io experimental-sstl15 --build-dir build-uberddr3-split \
  --controller-mhz 83.333 --onehot --pipeline-bist --seed 2
.venv-ddr-compat/bin/python tools/kc705_set_internal_vref.py \
  --build-dir build-uberddr3-split \
  --db-root build-vexriscv/prjxray-db/kintex7
```

Omit `--controller-mhz 83.333` for the 100/400 MHz profile. The split profile
keeps a 100 MHz system clock running alongside the slower DDR controller; LED 7
shows its heartbeat. When connecting the CPU and other blocks, use the existing
[100/83.333 MHz request/response CDC](../kc705_vexriscv/DDR.md#separate-cpu-and-ddr-clocks).
That bridge has already passed simulation with 9,294 reads and 8,400 writes.
Those blocks remain disconnected while this standalone memory target is tested.

The build also accepts `generate` and `synth` stages, `--mapper abc|abc9`,
`--placer heap|sa`, and explicit paths for Yosys, nextpnr and the chip database.
It writes source provenance, XDC, synthesis scripts, logs, the mapped netlist,
and routed FASM. It checks structural correctness before and after mapping,
then rejects timing failures even when nextpnr exits with status zero. Export
must use the same current Project X-Ray database used by the KC705 LiteDRAM
build; the older `/tmp/kc705db` snapshot is incomplete for I/O feature encoding.
The working export command is:

```sh
python3 tools/kc705_export_bitstream.py --build-dir build-uberddr3-split \
  --db-root build-vexriscv/prjxray-db/kintex7
```

The resulting image was loaded to FPGA SRAM with `openFPGALoader -b kc705`;
this does not write board flash. LED 0 indicates PLL lock, LED 1 indicates a
clean BIST completion, LED 2 indicates failure/timeout, LEDs 6:3 show the low
calibration-state nibble, and LED 7 is the 100 MHz system heartbeat. Check LED 1
and LED 2 on the physical board to determine the memory result.

For write-level diagnosis, build with `--diagnostic-wl`. In this image LED 6 is
the sampled feedback bit and LEDs 5:3 show the active byte lane as a binary
number. A changing lane indicates calibration is advancing. On watchdog
timeout, LEDs 7:3 freeze the active data ODELAY tap as a five-bit value.
The timeout snapshot showed tap 31 with no feedback transition on lane 0. The
current diagnostic build also enables DRAM ODT before beginning DQS write
leveling, following the Micron DDR3 write-leveling sequence.

The `kc705_uberddr3` and `kc705_uberddr3_pipeline` CTest entries are available when
Python, Yosys and Icarus are found. Each runs 20 BIST scenarios plus the equivalence
proof and status tests. Verification covers:

- SAT proof of byte-mask rewrite equivalence for all 512-bit data inputs and
  all 64 byte positions.
- SAT proof that the partial comparisons detect exactly the same mismatches
  as a full-width comparison, for every pair of 512-bit data inputs.
- Real controller BIST generation/checking against an abstract, backpressured
  memory service: 256 checked reads, 4,288 writes, 4,096 single-byte writes.
- Detection of corrupted first and final reads and a memory service that ignores
  byte masks, plus corruption at eight positions spread across the 512-bit data.
- All seven phases of the backpressure pattern with 24-cycle response latency,
  including corruption of a delayed final read.
- Sticky failure reporting, clean completion, completion without verified reads,
  simultaneous success/error, timeout, retry, and external reset.

The BIST regression bypasses initialization/calibration and the PHY, and uses
the upstream simulation option to shorten the address-counter range. It is
**not** a DDR3 protocol/PHY simulation or a physical memory test. Production
builds retain `MICRON_SIM=0` and the full 24-bit burst address.

## LEDs and acceptance

| LED | Meaning |
| --- | --- |
| 0 | PLL locked |
| 1 | Built-in test completed with verified reads and no observed error |
| 2 | Sticky BIST error or watchdog expiry |
| 6:3 | Low four bits of calibration state |
| 7 | 100 MHz system clock heartbeat |

A failure overrides success and remains latched through the controller's
internal retries. Board reset clears the wrapper's status; reprogramming also
clears upstream counters. The pinned upstream error counter survives controller
reset, so a prior memory error may remain visible after pressing reset.

Upstream BIST mode 1 divides its counter range among masked bursts, row-changing
accesses and alternating writes/reads. Its data pattern repeats every 256 burst
counter values; it does not establish freedom from all high-address aliasing.
A repeatable board pass plus independent address-alias tests is needed before
using DDR3 as general system memory or reconnecting the CPU and other blocks.

## Current results

The initial 100 MHz route reached 75.05 MHz. Rewriting the byte-mask selection
improved the ABC9 route to 78.87 MHz; the ABC mapper reached 81.02 MHz. These
three routes predate the final-read correction and are comparison evidence only.
With the final-read correction, one-hot state encoding reached 84.49 MHz and
the first pipelined checker reached 87.05 MHz. Adding the response-completion
guard reached 90.12 MHz; byte-level comparison registers reached 91.62 MHz
with seed 4. A placement-seed search with the final RTL reached **97.56 MHz**
with seed 2 (`build-uberddr3-seed2/`). The simulated-annealing placer failed
nextpnr's internal placement validity check. Earlier variants are comparison
evidence, not timing sign-off for the current RTL.

The current source hashes match the seed-2 routed build. **The 100 MHz target
is not met.** The route guard correctly rejects the image. Both controller-test configurations
(20 scenarios each), both SAT equivalence checks, status tests and route-guard
tests pass. These results do not establish physical memory operation.

| Final RTL placement seed | Routed controller Fmax |
| --- | --- |
| 0 | 84.62 MHz |
| 1 | 79.37 MHz |
| 2 | 97.56 MHz |
| 3 | 93.85 MHz |
| 4 | 91.62 MHz |
| 7 | 96.39 MHz |

The 83.333 MHz controller profile now routes successfully while retaining a
100 MHz system clock. With seed 2, nextpnr reports 88.63 MHz controller Fmax and
520.83 MHz system-clock Fmax; this passes the requested frequency guard. The
DDR output clock is 333.333 MHz. The controller profile is selectable with
`--controller-mhz 83.333`.

The selectable 83.333 MHz controller / 333.333 MHz DDR profile keeps the system
clock at 100 MHz. Timing is routed, the frame roundtrip passes, and the image
has been loaded to the board. Physical DDR3 status remains unobserved remotely;
LED 1 should be on for BIST pass, LED 2 on for failure/timeout. No physical
DDR3 pass is claimed until that status is observed.

The ODT-sequencing experimental image (`build-uberddr3-odtfix/soc.bit`) was
written to the KC705's Micron N25Q128 configuration flash with openFPGALoader
and its SPI readback verification passed. The open-source upstream
`spiOverJtag_xc7k325tffg900.bit.gz` bridge was used because the installed
Homebrew bridge bundle did not include the FFG900 package variant. Flash
programming success confirms storage only; DDR3 calibration and BIST still
need to be checked from the board LEDs after a power cycle.

The latest physical observation (all LEDs except LED1 on) corresponds to
write-level timeout at ODELAY tap 31 without feedback, not a BIST pass. Source
inspection found that ROM instruction 17 disables MR1 write leveling while the
FSM pauses on instruction 17 to pulse DQS. The build now suppresses that MRS
until training succeeds, then allows the original MRS followed by its tMOD
wait. The corrected image routes at 89.04 MHz for the 83.33 MHz controller,
passes the BIST/status regressions and frame roundtrip, and has been written to
configuration flash with SPI readback verification. Physical DDR3 calibration
and BIST remain unconfirmed.

The USB-UART diagnostic image gives more precise evidence. It is loaded into
FPGA SRAM over JTAG; it does not replace the flashed image. The KC705 CP2103
UART is `/dev/cu.usbserial-0001` on the current host. Capture with:

```sh
.venv-ddr-compat/bin/python tools/kc705_uberddr3_capture_uart.py \
  --bit build-uberddr3-uartdiag-preserdes/soc.bit \
  --out build-uberddr3-uartdiag-preserdes/capture-1 \
  --observe-seconds 20
```

The routed diagnostic image passed the 83.333 MHz controller and 100 MHz
system timing guards and the bitstream frame roundtrip. Its 20-second capture
decoded 20,168 frames. IDELAYCTRL/DCI reported ready; ODT, DQS drive, and DQ
input mode were requested; the write-level tap scanned 0 through 31 repeatedly.
The controller also requested DQS toggles. Both the DQ0 signal just after
IDELAY and the sampled ISERDES DQ0 remained low throughout; no write-level
feedback high was observed. This rules out loss solely in the ISERDES output,
but does not establish that the DRAM saw a valid CK/MRS/DQS waveform or that
the board input has the expected voltage. The current openXC7 build substitutes
SSTL15 for the KC705's DQ `SSTL15_T_DCI` requirement, so FPGA-side DQ
termination remains an unresolved hardware difference. A DIMM/power or
command/output-path issue also remains possible. Do not claim DDR3 calibration
or BIST success from this capture.

After the board was powered off and back on, the same SRAM diagnostic image was
loaded again. The second 20-second capture (`capture-after-powercycle/`) decoded
20,124 frames and produced the same result: lane 0 swept taps 0–31, DQS toggles
were requested, and neither the pre-ISERDES nor ISERDES DQ0 ever went high.
Power cycling did not resolve the write-level feedback failure.
