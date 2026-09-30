# Synapse32 + tiny3tpu + KC705 DDR3 bring-up

This is an open-source-only path: LiteDRAM K7DDRPHY, Yosys with the Slang
SystemVerilog frontend, and openXC7 nextpnr. No Vivado or MIG is invoked.

**Do not equate simulation or synthesis with working board DRAM.** Physical
calibration, timing closure, termination configuration, and repeated board
memory tests are separate gates. The build driver deliberately does not flash
the board or bypass timing failures.

Known physical-build blocker: installed nextpnr `68aeeb3` warns that
`get_iobanks` is unsupported and ignores the required `DCI_CASCADE` constraint,
even while returning success. The build driver rejects that warning. DDR
termination must be implemented and verified in the open-source toolchain
before any resulting image is programmed; deleting the constraint is not a fix.

## Architecture

`kc705_synapse32_top.sv` combines the generated x64 DDR3 controller with the
Synapse32/TPU system. Synapse32 boots from synchronous block RAM and initializes
the controller through its CSR bus. It is not held waiting for DDR calibration:
that would deadlock the initialization firmware itself.

| CPU byte-address range | Purpose |
| --- | --- |
| `0x80000000..0x8000ffff` | 64 KiB boot RAM, firmware data, BSS, stack |
| `0x40000000..0x7fffffff` | 1 GiB uncached DDR window |
| `0xf0000000..0xf000ffff` | LiteDRAM initialization/calibration CSRs |
| `0x20000000..0x2000001f` | Synapse32 UART, aligned word register accesses |
| `0x20001000..0x2000101f` | TPU AXI-Stream command mailbox |
| `0x20002000` | Bring-up completion code / debug output |
| `0x20002004` | Bring-up result trace / debug output |

The generated DDR user bus uses word addresses relative to DDR base; its control
bus uses word addresses relative to CSR base. The board wrapper performs both
translations. DDR reads request all four byte lanes. CPU byte/halfword stores
are shifted from Synapse32's low-justified format to aligned memory byte lanes.

### CPU memory latency

The existing CPU has no external memory-ready input. The memory sequencer
finishes each data access and instruction fetch before enabling the next CPU
clock edge through a dedicated `BUFGCE`. UART, TPU, and DDR continue to run on
the system clock. This is deliberately slow, uncached bring-up, not a throughput
optimization. The gated clock must be timed as related to the system clock;
there are no broad false-path or timing-allow-fail exemptions.

`SYNAPSE32_CLOCK_SIM` selects a falling-edge-latched clock-enable simulation
model. Never define it for physical synthesis. Physical builds instantiate
`BUFGCE`, not a fabric AND gate. Reset must reach the CPU's synchronous PC reset
through enabled clock edges. All memory targets must share the coordinated reset.

Firmware is bare-metal M-mode, RV32I + Zicsr/Zifencei, ILP32. No MMU, atomics,
cache coherency, or asynchronous interrupt support is claimed by this board
integration. CPU cycle counters count enabled CPU clocks, not wall time.

### DDR configuration and firmware

The provisional configuration assumes the original KC705 **MT8JTF12864-family
1 GiB, single-rank, x64 DDR3 SODIMM**, with 14 row, 10 column and 3 bank bits.
Confirm the fitted module before programming this configuration. Controller
clock is 100 MHz; DDR CK is 400 MHz (800 MT/s); IDELAY reference is 200 MHz.

Pins, SSTL15/DCI requirements, VCCAUX_IO, and DCI cascade are generated from the
installed LiteX-Boards KC705 definition. The build does not silently substitute
unterminated I/O standards. The standalone LiteDRAM generator's placeholder
`LOC=X` constraints must not be used as board constraints.

`ddr_boot_support.c` links the pinned LiteDRAM `sdram.c` and `accessors.c`, with
UART logging and a local memory test. DDR `block_until_ready` is intentionally
false: upstream `sdram_init()` performs its memory test before setting its
software `init_done` CSR. Only the trusted initializer accesses DDR before that
completion flag. Models must not be loaded until calibration and memory testing
succeed. A second initializer CPU is not needed.

The destructive self-test runs before application data is loaded. It checks
sparse address-line probes across the 1 GiB window, 16 KiB of patterned/inverted
data, and byte/halfword masked writes across all eight physical byte lanes. It
is not exhaustive capacity, refresh-retention, temperature, or margin testing.
The firmware then runs a signed 5x11x7 TPU GEMM, with A/B/output in DDR, and
compares all 35 outputs. UART prints completion/failure diagnostics at 115200
baud. This is a bring-up image, **not yet a generic UART model-upload server**.

LEDs: 0 PLL lock, 1 DDR init done, 2 DDR init error, 3 CPU/bus fault,
4 firmware finished, 5 firmware success, 6 reserved, 7 system heartbeat.

## Build

The local compatible generator environment is `.venv-ddr-compat` (Python 3.9).
Dependencies are pinned in `requirements-ddr.txt`. The Python files generate HDL;
they do not replace the C++ compiler or the C firmware.

```sh
.venv-ddr-compat/bin/python tools/kc705_open_build.py generate \
  --synapse32-dir /path/to/synapse32
.venv-ddr-compat/bin/python tools/kc705_open_build.py firmware \
  --synapse32-dir /path/to/synapse32
.venv-ddr-compat/bin/python tools/kc705_open_build.py route \
  --synapse32-dir /path/to/synapse32
```

Stages are cumulative. Outputs/logs are in `build-ddr` by default. Tool and
chip-database paths can be overridden with command-line options. The default
nextpnr is the installed openXC7 build; do not infer its capabilities from an
older unrelated source checkout. Installed revision `68aeeb3` includes ODELAY
packing, unlike the older local source that was initially inspected.

The Synapse32 source tree is referenced without modification. Slang is needed
for its cross-module CSR references and declaration ordering. Only the CPU is
elaborated with Slang; the classic frontend reads board RTL, boot RAM, and
generated LiteDRAM (whole-board Slang cannot handle this primitive/RAM path).
Primitive cells
are resolved against the Xilinx library, then `hierarchy -check` verifies that
no unresolved modules survive. Never replace the CSR references with undriven
wires merely to make the classic Verilog frontend accept the source.

The last calibration firmware build occupied approximately 12.9 KiB including
data/BSS, within the 64 KiB boot memory. The linker reserves at least 4 KiB for
stack. The split-frontend whole-board synthesis passed `check -assert` and
mapped 16 `RAMB36E1` primitives. This does not establish timing closure.

## Verification

```sh
cmake -S . -B build-stream \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python" \
  -DTINY3TPU_SYNAPSE32_DIR=/path/to/synapse32
cmake --build build-stream -j 4
ctest --test-dir build-stream --output-on-failure -j 3
```

The 24-test regression includes the original compiler/runtime/JAX/TPU tests,
sequencer and Wishbone unit tests, and actual Synapse32 CPU execution against
variable-latency external memory. The latter passed with 9,294 reads, 8,400
writes and 35 independently checked signed matrix results. It models memory
transactions, not physical DDR strobes or calibration.

Before calling this board-ready, require a reviewed electrical configuration,
successful implementation and timing analysis, a generated bitstream, UART
calibration logs, memory tests surviving refresh and repeated resets, and an
actual hardware TPU result comparison. End-to-end JAX upload to this physical
board remains a later integration gate.

References: [LiteDRAM](https://github.com/enjoy-digital/litedram),
[LiteX KC705 target](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/targets/xilinx_kc705.py),
[KC705 user guide](https://docs.amd.com/v/u/en-US/ug810_KC705_Eval_Bd).
