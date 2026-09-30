# Upstream KC705 DDR reference experiment

This isolated experiment reproduces openXC7/demo-projects commit
`0683680d50a1b80a12654e6d8e8ea7a1e2e2b3fe`, directory `litex-ddr-kc705`.
The upstream RTL, memory initialization files, and XDC are unchanged.
VexRiscv is the upstream test harness, not a replacement for Synapse32.

Upstream uses plain SSTL15 on DQ and comments out DCI_CASCADE. Treat this as
an experimental alternative electrical configuration, not proof of working
termination or reliable memory. The Synapse32 board constraints remain intact.

Local checkout/build: `/tmp/tiny3tpu-kc705-ddr-upstream/litex-ddr-kc705`.
Stock target: KC705 xc7k325tffg900-2, 1 GB DDR3 SODIMM.
Upstream PLL settings produce 125 MHz system / 500 MHz DDR clock.

Synthesis command (run from the upstream example directory):

```sh
/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys -Q -T -l synth.log \
  -p 'synth_xilinx -flatten -abc9 -family xc7 -top xilinx_kc705; check -assert; write_json xilinx_kc705.json' \
  xilinx_kc705.v ../vexriscv/VexRiscv.v
```

Hardware acceptance requires the separate USB-UART connection, calibration
logs, a passing memory test, repeated resets, and extended memory stress.
The Digilent JTAG USB adapter alone is not the board's Silicon Labs UART.
Do not infer hardware success from LEDs, synthesis, or a generated bitstream.
Use volatile JTAG loading only; leave configuration flash and the existing
blink artifacts unchanged.

## Local reproduction results

The unchanged reference passed synthesis (`check -assert`: zero problems),
placement/routing, and FASM-to-frames conversion with the installed tools.
However, its route reported only 75.95 MHz for the system clock while declaring
PASS against a 12 MHz default. The hardware PLL actually runs that domain at
125 MHz. That output is diagnostic only, not qualified for programming.

`clocks.py` is a separate nextpnr `--pre-pack` overlay that explicitly constrains
input/system/DDR/IDELAY clock nets. It does not change the reference RTL or XDC.
Use `--freq 125` as the fallback in addition to that overlay, and retain timing
failures. The ignored upstream `set_false_path` is not replaced with a broad
exception. Correct internal clock constraints still do not establish external
DDR setup/hold margins.

UART settings: 115200 baud, 8N1, no hardware flow control. Upstream embedded
LiteX BIOS contains DDR calibration, Memtest OK/KO, and `sdram_test`/`mem_test`
commands. These strings are firmware evidence, not observed hardware output.

The explicitly constrained rerun also completed routing but reported
**75.95 MHz, FAIL at 125 MHz** for `main_crg_clkout_buf0`, despite exiting zero.
Do not rely on the process exit code or program `timed.fasm` output. Both local
routes are unqualified; no FPGA image was loaded. The next implementation gate
is closing real system timing (or regenerating a lower-rate design with matching
DDR and firmware timing), not deleting clock constraints.

The follow-up `--placer-budgets` experiment retained the same RTL and explicit
clock overlay but worsened final system Fmax to 67.26 MHz. It is not a fix.
The baseline critical path contains 1.2 ns logic and 12.0 ns routing, from the
CSR address decode to a PHY bitslip-counter enable. Further work should focus
on placement/locality or a protocol-preserving registered CSR decode, not
changing DDR timing constants independently of firmware/controller generation.

`tools/kc705_open_build.py` now explicitly rejects `FAIL at` timing messages
even with a zero process exit code. CTest `kc705_route_guard` covers this and
the ignored-XDC-property failure. This filter does not prove complete timing
coverage or qualify an image for hardware.

The classic ABC / `-nowidelut` synthesis experiment (without `-abc9`) used
unchanged RTL, firmware and the same clock overlay. Structural synthesis checks
passed and final routed system Fmax improved to 79.62 MHz, still FAIL at 125 MHz.
Logs/netlists use the `classic-*` / `classic.json` names in the reference
checkout. No timing exception, retiming, or pipeline stage was added.
This remains unqualified. A lower-rate variant must regenerate the PHY/controller
timing and BIOS together, respecting the stock DDR3 module's supported range;
changing only the PLL or relaxing the timing target is not a valid adaptation.

## Placement seed sweep

All runs below use identical `classic.json` (SHA-256
`39685f836d6a7e357a128310761b2db67c877cbdf1dde10888db73e986cfd199`),
the unchanged upstream XDC, and `clocks.py`. No timing exceptions or clock
reductions are added. Reproduce from the upstream example directory:

```sh
/Users/siriboi/.apio/packages/openxc7/libexec/nextpnr-xilinx \
  --chipdb /tmp/openxc7-blinky-full/xc7k325tffg900-2-apio.bin \
  --xdc xilinx_kc705.xdc --json classic.json \
  --pre-pack /Users/siriboi/github/tiny3tpu/hardware/kc705_ddr_reference/clocks.py \
  --freq 125 --seed 4 --fasm seed4.fasm --log seed4-route.log
```

Use the **last** frequency report (after routing), not the placement estimate.
The original classic run reports 79.62 MHz. Seeds 2, 3, and 4 report 80.00,
77.20, and 83.98 MHz respectively; all fail the 125 MHz requirement.
Seed 4's worst path moves into VexRiscv branch/fetch control (1.4 ns logic,
10.5 ns routing), so the earlier CSR decode is not the only limiting path.
The second batch (seeds 8, 16, 32) reports 73.08, 82.18, 68.97 MHz respectively.
All six processes completed routing and returned zero despite timing failure.
Seed 4 remains best at 83.98 MHz, about 5.5% above the original classic run,
but still needs its 11.9 ns critical path reduced below the 8 ns target.
No seed output was programmed. Further blind seeds have no demonstrated path
to closing this gap; investigate constrained placement/locality next.
