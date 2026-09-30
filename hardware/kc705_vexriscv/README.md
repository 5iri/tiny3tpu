# KC705 VexRiscv + tiny3tpu

VexRiscv Lite replaces the clock-gated Synapse32 CPU in this alternative board
build. CPU, boot RAM, interconnect and TPU share a **100 MHz** system clock.
The original Synapse32 board build remains selectable.

**Board result, 2026-09-26:** the 100 MHz boot-RAM CPU/TPU image was programmed
over JTAG and passed the signed GEMM and UART self-tests on two consecutive
programming runs. [Bring-up results](BRINGUP.md) record the exact image, tools,
timing limits and remaining DDR blocker.

The pinned generated RV32IM core is in
[third_party/vexriscv](../../third_party/vexriscv/UPSTREAM.md). It has an instruction
cache and an uncached data port. The UART RTL still comes from the adjacent
Synapse32 checkout; none of that checkout's CPU RTL is used here.

The interconnect captures a complete Wishbone beat before decoding it. Instruction
and data masters arbitrate round robin between beats, including instruction-cache
refills. Responses are registered, ACK and ERR are mutually exclusive, and
external requests remain stable under backpressure. There is one outstanding
transaction. An error also sets the sticky fault LED. `pc_debug` is the instruction
refill address, not the retired PC.

| Byte address | Target |
| --- | --- |
| `0x80000000–0x8000ffff` | 64 KiB synchronous boot RAM, byte write enables |
| `0x40000000–0x7fffffff` | 1 GiB DDR window |
| `0xf0000000–0xf000ffff` | LiteDRAM controller/PHY CSRs |
| `0x20000000–0x2000001f` | UART, 115200 baud |
| `0x20001000–0x2000101f` | TPU AXI-Stream mailbox |
| `0x20002000`, `0x20002004` | Exit code and result reporting |

The CPU starts before DDR calibration so firmware can initialize the PHY through
its CSRs. The no-DDR build returns an error for every external access. Its PLL and
firmware UART divisor both use 100 MHz.

The PE accumulator now uses a reset-free DSP payload with an asynchronously reset
valid bit. Visible reset, clear, signed arithmetic and overflow behavior remain
cycle-equivalent; no MAC cycle was added. All 32 PEs synthesize with DSP `PREG=1`.

## Build and test

```sh
# Use the existing isolated LiteDRAM/LiteX 2024.12 Python environment.
# The default VexRiscv router is the qualified local DSP timing build below.
.venv-ddr-compat/bin/python tools/kc705_open_build.py route \
  --cpu vexriscv-lite --synapse32-dir ../synapse32 --no-ddr \
  --build-dir build-vexriscv/noddr \
  --chipdb /path/to/xc7k325tffg900-2.bin --seed 4

# Omit --no-ddr for the DDR controller and calibration firmware.
# See DDR.md for the stock DCI blocker and explicit experimental IO profile.
# Functional checks (the dram mode models RAM transactions, not a DDR PHY):
python3 tools/kc705_vexriscv_sim.py noddr --synapse32-dir ../synapse32 --out build-vexriscv/sim-noddr
python3 tools/kc705_vexriscv_sim.py dram --synapse32-dir ../synapse32 --out build-vexriscv/sim-dram
python3 tools/kc705_vexriscv_sim.py interconnect --synapse32-dir ../synapse32 --out build-vexriscv/sim-bus
python3 tools/kc705_vexriscv_sim.py wide --synapse32-dir ../synapse32 --out build-vexriscv/sim-wide
```

The tested router is OpenXC7 `nextpnr-xilinx` commit
`0eae9fbb19dfb83cdd30d5048d8b0ba744180ad0`, with the local DSP model added by
`tools/synapse32_build_dsp_preg_timing_inversions.py --grade2`. Its executable is
`build-vexriscv/nextpnr-preg-grade2/nextpnr-xilinx`; use `--nextpnr` to select another
explicitly checked build. Rebuilding that model requires a built checkout of
that commit and the verified DS182 files under `build-dsp-preg-timing`:

```sh
python3 tools/synapse32_build_dsp_preg_timing_inversions.py \
  --source-dir /path/to/nextpnr-xilinx --grade2 \
  --out build-vexriscv/nextpnr-preg-grade2
```

The tested frame database is `openXC7/prjxray-db` commit
`517d66a383676cb971177ea92b0ff3b6ea6e8690`. After a successful route:

```sh
python3 tools/kc705_export_bitstream.py --build-dir build-vexriscv/noddr \
  --db-root /path/to/prjxray-db/kintex7
openFPGALoader -b kc705 build-vexriscv/noddr/soc.bit
```

This programs volatile FPGA configuration RAM. No SPI flash is written.

The CMake suite exposes `vexriscv_noddr`, `vexriscv_dram`, `vexriscv_wide` and
`vexriscv_interconnect` when `TINY3TPU_SYNAPSE32_DIR` is provided. The directed bus
test uses test-only masters to check simultaneous continuous bursts, fairness,
byte enables, delayed requests/responses, DDR/CSR selection, errors and reset.
The two firmware tests instantiate the real CPU and TPU.

## Timing and programming status

Native nextpnr timing is incomplete for this device. In particular, its usual
DSP model ignores registered accumulators. A separate model adds the supported
PREG MAC profile using conservative limits from AMD DS182 Table 35; unsupported
profiles are rejected. The tested build selects the **-2/-2LE, 1.0 V column**
for the KC705's -2 device (A/B setup 3.90 ns, C setup 1.49 ns, clock-to-Q 0.35 ns).
The model also recognizes provably constant LUTs inserted by the router.
That still does not provide complete BRAM, clock-skew,
hold or DDR I/O analysis. Board self-tests and timing estimates are reported
separately; neither is a substitute for complete timing closure.

The stock DCI profile must honor the board's DCI cascade constraint. A warning that
`get_iobanks` is unsupported is a build failure, not permission to drop that
constraint. The explicit experimental SSTL15 profile and the new full-width
memory adapter are described in [DDR.md](DDR.md). See the build logs for the
exact status of each image.

## Ethernet follow-up

Ethernet is not implemented in this image. An MMIO MAC can become another
registered target. A DMA-capable MAC additionally needs arbitration on the DDR
data path and clock-domain crossings/FIFOs for its PHY clocks. The current
uncached CPU data port simplifies DMA buffer visibility; executable data still
requires instruction-cache maintenance. Preserve byte-address/word-address
conversion at the Wishbone boundary, and keep calibration CSRs accessible before
DDR is ready.
