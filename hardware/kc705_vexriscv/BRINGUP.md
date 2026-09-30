# KC705 VexRiscv bring-up — 2026-09-26

The last fully verified image runs **VexRiscv Lite + tiny3tpu at 100 MHz from boot RAM**.
The registered Wishbone interconnect and DSP accumulator change are implemented.
DDR and Ethernet are not active in that image. DDR diagnostic images are now
being loaded during bring-up; see [DDR.md](DDR.md) for their current failures.

Hardware UART at 115200 baud, observed on two consecutive JTAG programming runs:

```text
tiny3tpu noddr bringup: UART alive
mailbox OK
GEMM 5x11x7 PASS
SELFTEST PASS
```

The JTAG chain identified `xc7k325t`, IDCODE `0x03651093`. Programming completed
with `isc_done=1`, `init=1`, `done=1`. This is volatile configuration RAM; power
cycling clears this image. No nonvolatile flash was changed.

## Exact artifact and evidence

- Bitstream: `build-vexriscv/kc705-vexriscv-100mhz.bit`.
- SHA256: `2ddae24c79556b59d46cd1b24d6e69738f7e9bb399c6a7be01906cd513528825`.
- Full route, frame roundtrip, programming and UART evidence:
  `build-vexriscv/noddr-v6-preg/`.
- First and repeat run: `first-hardware-result.json`, `hardware-result.json`;
  matching UART logs and programming logs are in the same directory.
- Summary: `build-vexriscv/summary.json`.

The route reports **101.14 MHz at a 100 MHz constraint**, with all 32 DSP PREG
profiles explicitly modeled using AMD DS182's -2/1.0 V limits. The report's
earlier placement estimate was 88.26 MHz; the final routed report supersedes it.
The build guard checks the last report for every clock and rejects missing
reports, ignored constraints, implementation errors and final timing failures.

The bitstream was decoded back into 28,292 frames and compared with 27,850 input
frames. Every non-ECC input word matched; extra frames contained zero data.
This verifies the bitstream file, not device configuration readback.

The normal installed nextpnr reported 114.21 MHz for another route of the same
RTL but that image failed GEMM on hardware. The passing image uses the recorded
OpenXC7 source build plus the DSP timing model. Placement, routing and backend
differ between these images, so this does not isolate which difference caused
the first failure. Do not substitute the failed native image merely because
its frequency report is higher.

## Functional validation

- PE formal cycle equivalence against the preserved original RTL passed.
- Xilinx primitive simulation passed 204,138 comparisons, including signed
  products, clear, between-edge reset pulses and accumulator overflow.
- Real VexRiscv firmware with randomly stalled memory passed 9,294 reads,
  8,400 writes and all 35 signed GEMM outputs.
- Exact programmed boot firmware passed simulation and UART decoding at
  100 MHz/115200 baud before programming.
- Directed interconnect tests passed concurrent continuous instruction/data
  bursts, round-robin fairness, byte writes, stable backpressured requests,
  delayed responses, DDR/CSR selection, errors and reset.
- Six selected CTests passed, including the existing Synapse32 DRAM regression
  and TPU AXI/mailbox tests. The three VexRiscv tests were rerun after the last
  interconnect change and passed. Nine route-guard tests and three grade-column
  selection tests also passed.

## DDR and timing limits

The original combined DDR image was synthesized and routed at a 100 MHz target.
Its native route (`build-vexriscv/ddr-v6/route.log`) reports **80.04 MHz** for
the system clock. Its critical path is inside LiteDRAM's native-port width
converter/write-data path. The earlier combined route reported 89.24 MHz with
a controller command/timing path limiting it. CPU replacement alone therefore
does not close the combined DDR design.

The router additionally ignores the required `DCI_CASCADE {32 34}` constraint
on bank 33 because `get_iobanks` is unsupported. The build rejects this, and the
DDR image was not programmed. Controller timing and correct DDR I/O constraint
support remain necessary before physical DDR calibration/testing.

The follow-up DDR integration uses a registered 32-to-512-bit adapter and
formally checked LiteDRAM command-ready factoring. With registered SoC window
decode/CPU acknowledgements and bounded TPU counters, it has reached
**98.76 MHz** (`build-vexriscv/ddr-ack-seed2/route.log`), still below the target.
The split-clock follow-up passes timing at 100 MHz CPU/TPU and 83 1/3 MHz DDR
controller, reporting 107.98 and 93.41 MHz respectively. It has been programmed,
but physical read calibration and the memory test fail. The explicit experimental SSTL15 profile
omits FPGA DCI termination; its export flow also corrects the backend's internal
VREF setting to use the KC705's external 0.75 V reference. No DDR candidate has
yet passed hardware calibration or memory tests. See [DDR.md](DDR.md) for the
new interface, proofs, I/O profile and export checks.

The passing CPU/TPU image and two board self-tests establish this bring-up
result. They do not prove complete PVT timing closure: the open-source backend
still lacks full primitive, hold and clock-skew analysis. There is no new claim
of physical DDR correctness.
