# DDR3 first: a hardware-only KC705 test target

The alternative [UberDDR3 trial](../kc705_uberddr3/README.md) evaluates the same
100 MHz target using a hardware BIST engine and an entirely open-source flow.

This is the first stage for the post: the KC705's 1 GiB DDR3 SODIMM driven by
LiteDRAM and a finite-state test engine. The external connections are the
200 MHz oscillator, reset button, DDR3 pins, and eight status LEDs. There is
no processor, boot firmware, UART, TPU, DMA, or Ethernet in this target.

```text
200 MHz oscillator -> PLL -> 100 MHz test engine / controller
                         -> 400 MHz DDR clock
                         -> 200 MHz IDELAY reference

initialization / training FSM -> private 32-bit CSR wires -> LiteDRAM PHY
pattern generator / checker  -> private 512-bit memory port -> controller -> DIMM
                            -> sticky status LEDs
```

The two private interfaces use Wishbone handshakes. They are not connected to
a CPU or shared system interconnect. The 512-bit port transfers a complete
64-byte DDR burst, avoiding the earlier narrow-port adapter and clock crossing.

## What the engine does

1. Holds DDR reset low for at least 200 us, waits at least 500 us after release,
   raises CKE, programs MR2/MR3/MR1/MR0, and issues ZQCL. Waits are actual
   controller cycles, not firmware delay-loop counts. Mode-register values
   come from the generated PHY/controller settings. The explicit reset also
   covers reprogramming an already powered board.
2. Enables write leveling, samples each tap eight times, and finds a stable
   low-to-high transition independently on all eight byte lanes. It applies
   the selected DQ/DQS delays and exits write-leveling mode.
3. Uses ordinary controller writes and reads to scan all eight write bitslips,
   eight read bitslips, and 32 input-delay taps. Each candidate must match
   eight patterned transactions on every bit of its lane. It selects the
   center of the longest contiguous passing window per lane, requiring at
   least three taps. A changing pattern distinguishes stale readback.
4. Fills and verifies 25 sparse burst addresses (zero plus all 24 burst-address
   bits), then eight 256 KiB windows spanning the DIMM, including its final
   burst. Both sets use address-dependent patterns and their inverses. Each
   complete set is filled before verification to expose address aliasing.
5. Exercises every one of the 64 byte enables individually and checks that
   unselected bytes retain their previous contents. Only then does PASS latch.

CSR and memory accesses time out after 65,536 controller cycles. Errors stop
the engine, preserve the first failure, and require reset to restart. A full
idle cycle separates accesses, including pulse-based delay CSRs.

Initialization timing and the distinction between MPR and arbitrary data are
described in [Micron's DDR3 FAQ](https://www.micron.com/sales-support/sales/faqs).
The generator uses the pinned local LiteDRAM/LiteX 2024.12 implementation and
the existing, equivalence-checked controller-ready transformation.

## Calibration limits

This is a bounded first implementation, not a replacement for all of LiteDRAM's
software calibration algorithms. It keeps the generated command clock delay,
read/write command phases, and read latency. It does not sweep those settings
or fine-tune DQ independently of the write-leveled DQS delay. Write leveling
requires an observed low-to-high edge; an all-high or all-low scan fails.
These conservative conditions can reject a usable DIMM and make the failing
stage visible for the next DDR-only experiment.

The current combined-system experiments have not passed ordinary DDR reads
and writes; see [the existing DDR evidence](../kc705_vexriscv/DDR.md). Moving
the test into hardware does not establish that the PHY or board issue is fixed.
The behavioral testbench supplies synthetic delay windows and RAM transactions;
it does not simulate DDR electrical behavior or prove physical calibration.

## Validation recorded on 2026-09-26

- The exact generated production engine passes **13 Verilator scenarios**:
  successful training/BIST, reset in flight, constant-high and constant-low
  write-level feedback, absent and too-narrow read windows, corrupted data,
  aliased addresses, broken byte enables, and CSR/memory errors and timeouts.
  Tests retain the real initialization waits, full bitslip/tap search,
  production watchdog, and full 2 MiB BIST. The model offers competing read
  windows to check selection of the longest window and its center.
- CTest `kc705_ddr_only` and the existing `kc705_route_guard` pass. Logs are in
  `build-ddr-only-checks/ddr-only/simulation/`.
- Yosys structural checks pass before and after technology mapping. The
  design has no DSP cells or boot RAM. Generated LiteDRAM repeats identical
  DFI-mask assignments; ordinary Yosys optimization merges them before the
  structural check.
- Both 100 MHz routes fail the guard: the initial wide-LUT route reports
  **71.57 MHz**, and the LUT6 route reports **71.72 MHz**. The first limiting
  path traverses LiteDRAM bank-command/ready logic, with 12.2 ns routing delay.
  Evidence is in `build-ddr-only-experimental/` and `build-ddr-only-lut6/`.
  The build now uses LUT6 synthesis; this is not timing closure.
- **No standalone image was programmed. No physical memory pass is claimed.**
  Timing remains the immediate implementation blocker. Existing physical PHY
  read/write failures also remain unresolved.

## LEDs

| LED | Meaning |
| --- | --- |
| 0 | PLL locked, or failure-code bit 0 when LED 5 is on |
| 1 | Controller reset released, or failure-code bit 1 |
| 2 | Initialization sequence completed, or failure-code bit 2 |
| 3 | Calibration settings selected; this alone is not a memory pass |
| 4 | Complete memory test passed (sticky) |
| 5 | Failure (sticky) |
| 6 | Engine busy |
| 7 | Heartbeat |

Failure codes: **1** CSR timeout/error, **2** no write-leveling edge,
**3** memory timeout/error, **4** insufficient read window, **5** data mismatch.
The engine also retains the failing burst address and lane mask as RTL outputs
for simulation or a future debug connection; only the LEDs are exposed on the
current board top.

## Toolchain requirement

Use open-source tools throughout generation, simulation, synthesis, routing,
bitstream creation, and programming. Vivado, ISE, and proprietary-tool-dependent
IP generation are excluded from this project flow. Alternative DDR3 IP must
work within that constraint; a reported clock rate achieved with a vendor
toolchain does not establish the same result with OpenXC7.

## Build and verify

```sh
.venv-ddr-compat/bin/python tools/kc705_ddr_only_build.py generate \
  --build-dir build-ddr-only
.venv-ddr-compat/bin/python tests/test_kc705_ddr_only.py \
  --build-dir build-ddr-only
.venv-ddr-compat/bin/python tools/kc705_ddr_only_build.py synth \
  --build-dir build-ddr-only
```

The generator requires no Synapse32 checkout, RISC-V compiler, or firmware
image. `hardware-manifest.json` records settings, dependency versions, source
hashes and the absence of a CPU and accelerator. The default BIST checks 2 MiB
plus sparse address probes; it is not an exhaustive capacity/retention test.

For CTest, configure with
`-DTINY3TPU_DDR_PYTHON="$PWD/.venv-ddr-compat/bin/python"` and run
`ctest --test-dir <build> -R '^kc705_ddr_only$' --output-on-failure`.

The default electrical profile retains the board's DCI constraints. The
current openXC7 backend cannot honor the DCI cascade, which remains a route
failure. The existing experimental profile is explicitly selectable:

```sh
.venv-ddr-compat/bin/python tools/kc705_ddr_only_build.py route \
  --build-dir build-ddr-only-experimental --ddr-io experimental-sstl15 \
  --chipdb /tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin
```

This profile has no FPGA DCI input termination. It must not be described as
stock DCI support. The route guard rejects ignored constraints, missing
frequency reports, and final timing failures even if nextpnr exits zero.
No command above programs the FPGA or writes configuration flash.

## Post scope and later connections

The first post milestone is a repeatable standalone DDR memory pass, with
the exact image, clock and I/O settings, reset repetitions, and observed LED
results recorded. Until then, report implementation and simulation separately
from physical hardware results. Initialization, an MPR pattern, or a passing
route is not the milestone.

After that milestone, add one connection per build and rerun the memory test:

| Stage | Add | Acceptance before the next stage |
| --- | --- | --- |
| 1 — current | DDR3 + hardware test engine | Ordinary data and byte-mask tests pass repeatedly on the DIMM |
| 2 | CPU access to DDR | CPU memory tests agree with the established hardware test |
| 3 | TPU control/data connection | Small DDR-backed GEMM matches a reference |
| 4 | DMA | Transfers and GEMM stay correct under backpressure and contention |
| 5 | Ethernet | End-to-end requests work while memory and accelerator checks still pass |

Keep the standalone target available as the reference at every later stage.
