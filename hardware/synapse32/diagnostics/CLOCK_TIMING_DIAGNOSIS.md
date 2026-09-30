# KC705 timing-check diagnosis — 2026-09-26

The reported failure is **nextpnr timing acceptance above 40 MHz**, not a
hardware boot, LED, or UART failure. Fresh synthesis and routing reproduce a
CPU timing estimate near that boundary after selecting the iterative-divider
overlay. The default CPU has a substantially worse combinational divider.
The user's deleted build cannot be identified byte-for-byte from this evidence.

## Fresh controlled comparison

Both builds use `kc705_noddr_top`, the same 40 MHz PLL settings, boot firmware,
XDC, seed 4, installed nextpnr `68aeeb3`, Yosys `0.63+173 / 66306a8ca-dirty`,
and `/tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin`.
Only the four CPU source substitutions selected by `--cpu-overlay-dir` differ.
These are native backend timing estimates, not measured hardware Fmax.

| CPU source selection | CPU estimate | System estimate | CPU worst interval |
| --- | ---: | ---: | ---: |
| Default adjacent Synapse32 checkout | 6.24 MHz | 51.36 MHz | 160.3 ns |
| Existing iterative-divider overlay | 44.11 MHz | 65.72 MHz | 22.7 ns |

A third, fresh place-and-route run on the divider-overlay netlist with
`--freq 50` reproduced **44.11 MHz CPU — FAIL at 50 MHz**, and **65.72 MHz
system — PASS at 50 MHz**. This was a timing-target experiment; PLL and
firmware remained configured for 40 MHz, and no hardware image was produced.
The command target did not change the final modeled path delay. Files:
`iterative-divider/route-target50.log` and
`iterative-divider/report-fresh-target50.json`.

Default synthesis still contains the combinational `/` and `%` operators.
The final CPU critical path traverses `div_mod.div_mod_u.chaindata`: 25.9 ns
logic and 134.4 ns routing. Selecting the divider overlay reduces CARRY4 count
from 1,781 to 354 and mapped cell count (including scope metadata) from 31,853
to 17,484. The default build therefore does not reproduce a 40 MHz CPU pass;
the divider-overlay build is the closer reproduction of the reported boundary.

With the iterative divider, the limiting CPU path is:

`EX/MEM instruction ID -> operand/result forwarding -> combinational signed
multiply -> ALU/execute result selection -> EX/MEM execution-result register`.

The final report assigns 7.9 ns to logic and 14.8 ns to routing. The mapped
CPU uses 12 DSP48E1 cells, all with `AREG=BREG=MREG=PREG=0`; the TPU uses 32
additional DSPs. No CPU multiplier pipeline register breaks this path.
At a 50 MHz target, the available single-cycle interval is 20 ns, shorter
than this route's 22.7 ns path. At 100 MHz it is only 10 ns.

The no-DDR system-domain path is 15.2 ns, from sequencer state through UART
address/control decoding to an RX FIFO write enable (2.4 ns logic, 12.8 ns
routing). CPU-to-system is 13.95 ns and system-to-CPU is 3.58 ns. Removing
the CPU multiplier bottleneck alone therefore does not establish 100 MHz
closure for the rest of the system.

## Clock-gating interpretation

The current timing check assigns a full-rate clock to `soc.cpu_clk`. It does
not infer a multicycle path from the sequencer's transaction protocol.
The actual no-DDR firmware simulation observed a minimum of **four system
cycles between enabled CPU edges** after reset. This agrees with the
sequencer's state transitions, but one workload is not an exhaustive timing
exception proof. CPU-to-system paths are sampled sooner and cannot simply
receive the same allowance as internal CPU-to-CPU paths.

Consequently the 44.11 MHz report explains the current timing rejection; it
does not establish that the board physically stops functioning above 40 MHz.
No timing exception or clock relaxation was installed.

The existing [system-clock multiplier experiment](../experiments/system-mul/README.md)
already explores using the intervening system edges for registered multiply
without adding enabled CPU edges. It is not enabled by the normal build
driver. Its historical results are not a fresh validation or a timing fix
from this investigation. The alternative stalling multiplier changes IPC,
as documented in [its experiment](../experiments/mul-pipeline/README.md).

## Checks executed

Four CTests passed: memory sequencer, Wishbone bridge, default CPU with
variable-latency memory, and iterative-divider CPU with the same memory model.
Each CPU workload checked 9,294 reads, 8,400 writes and 35 signed GEMM results
in 4,981,249 system cycles. This RV32I workload does not exercise hardware
multiply/divide, so it does not validate their physical timing.

The actual no-DDR firmware was also run against the CPU/TPU RTL with an
external UART decoder. It returned zero and matched all 35 GEMM outputs.
The harness models the digital SoC and clock enable, not PLL or cell delays.

An independent configuration issue was reproduced: firmware built for 40 MHz
produces undecodable UART at a simulated 50 MHz clock/115200-baud receiver,
while the computational self-test still passes. Recompiling only the firmware
clock constant for 50 MHz restores the UART banner and `SELFTEST PASS`.
This is **not the user's reported nextpnr failure**. `--freq` only sets a
timing target; it does not update the PLL or firmware clock constant.

An attempted saved-route replay at a 50 MHz target aborted during import with
`std::out_of_range / unordered_map::at`. It produced no valid timing result.
The completed original routes remain intact; the subsequent fresh target-50
place-and-route run completed and reproduced the failure as reported above.

## Evidence and reproduction

Fresh artifacts are in `build-clock-diagnosis/` at the repository root:

- `noddr/`: default synthesis, firmware, final route and JSON report.
- `iterative-divider/`: matching divider-overlay synthesis and route.
- `tests/Testing/Temporary/LastTest.log`: four passing CTests.
- `noddr-sim/`: executable harness, reproduction driver, commands and UART logs.
- `input-sha256.json`: 66 source, generated-input, tool and database hashes.

Build each source selection into a fresh directory:

```sh
.venv-ddr-compat/bin/python tools/kc705_open_build.py synth --no-ddr \
  --synapse32-dir /Users/siriboi/github/synapse32 \
  --build-dir build-clock-diagnosis/noddr
.venv-ddr-compat/bin/python tools/kc705_open_build.py synth --no-ddr \
  --synapse32-dir /Users/siriboi/github/synapse32 \
  --cpu-overlay-dir hardware/synapse32/experiments/divider \
  --build-dir build-clock-diagnosis/iterative-divider
```

For either directory, invoke installed nextpnr with `--chipdb` as above,
`--xdc DIR/kc705.xdc --json DIR/soc.json --seed 4 --freq 40`, and separate
`--write`, `--report`, and `--log` outputs. Inspect final `FAIL at` messages:
the completed default route exited zero despite failing CPU timing.

The surviving historical DDR route `/tmp/kc705db/route-kc705-s4.log` reports
CPU 5.73 MHz and system 46.17 MHz against 100 MHz, and an ignored DCI property.
It is separate evidence, not one of the fresh controlled no-DDR builds.

Production RTL, build defaults and the adjacent CPU checkout were not edited.
No board adapter was connected and no image was programmed. Existing backend
coverage limitations mean none of these reports establishes physical DDR or
whole-chip timing signoff.
