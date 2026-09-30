# RV32IM firmware optimized for useful work per system cycle

The retained firmware removes two sources of unnecessary command traffic and
CPU memory work:

- `tiny3tpu_dma_submit` uses the TDM1 aggregate ERROR/MISUSE bits after DONE,
  instead of rereading every command's status from DDR. DONE includes the final
  response write, and command/protocol/AXI errors are already aggregated by RTL.
- Result collection uses three commands per cell: select, capture, read LO.
  The stream bridge completes each transaction before the next. The fixed
  accelerator stores signed 32-bit results, so HI only repeats the sign bit;
  an intervening STATUS read is unnecessary. CPU accumulation remains 64-bit,
  with the original final signed-32-bit overflow check.

No RTL or ISA change is made in this round. Ownership checks, fences, bounded
polling, timeout poisoning and result verification remain. Packed-row capacity
falls from 160 to 96 commands; the legacy loader still needs 193. Both operand
paths benefit from the new completion/result code. Packed rows remain an
explicit build choice; `-O3` is the measured throughput-oriented compiler setting.

## Same 45 shapes, 3,022 checked results

All rows below perform the same 72,224 useful MACs. The baseline is the previous
packed-row firmware at `-Os`, not the older per-byte operand loader.

| Metric | Previous packed | New firmware, `-O3` |
|---|---:|---:|
| Total diagnostic system cycles | 27,336,085 | **15,601,564** |
| Useful MACs / total system cycle | 0.00264208 | **0.00462928** |
| GEMM-only system cycles | 18,677,625 | **9,541,773** |
| Pooled GEMM IPC | 0.820446 | **0.864774** |
| Equal-shape mean GEMM IPC | 0.784306 | **0.844598** |
| Useful PE capacity during GEMM windows | 0.012084% | **0.023654%** |
| DMA read beats (write beats equal) | 213,450 | **137,970** |

Whole-test throughput rises **75.2%** and elapsed system cycles fall **42.9%**.
GEMM-only cycles fall **48.9%**. All 45 shapes improve both GEMM time and CPU IPC
against the preceding packed firmware. Array utilization remains low: the
firmware improvement does not turn the command transport into a queued tensor
stream, nor eliminate short-tile loading and fill/drain overhead.

The compiler comparison also passes all 3,022 results:

| New firmware setting | Whole-test system cycles | Full-program IPC | Test image text+data |
|---|---:|---:|---:|
| `-Os` | 19,739,151 | 0.700938 | 6,032 bytes |
| `-O2` | 16,395,951 | 0.834328 | 6,604 bytes |
| `-O3` | **15,601,564** | **0.836714** | 13,300 bytes |

`-O3` improves 44 of 45 GEMM times over `-O2`; the tradeoff is larger code.
These figures include generated test firmware, not just the DMA backend.
The default legacy operand path at `-Os` also passes the sweep and falls from
41,346,388 to 27,158,433 whole-test cycles using the retained source changes.

## Validation

- All 45 shapes and 3,022 host/firmware-checked signed results pass for the
  legacy path and each packed compiler variant. Separate smoke tests pass.
- All 27 open DMA tests pass, including command and AXI errors, descriptor
  validation, coordinated reset and final-write completion.
- An actual RV32IM firmware test injects command errors at positions 0, 96 and
  192, checking failure return, acknowledgment, poisoning, rejected resubmission
  and explicit reinitialization, then executes the original GEMM scoreboard.
- Observation-only profiling reproduces exact firmware bytes and full profiles
  before deriving per-GEMM IPC and activity counters.

The denominator is system-clock cycles, including CPU clock-gated memory waits.
Full-test figures include diagnostic boot, input generation and verification;
GEMM-only figures exclude those caller phases. These are behavioral-memory
simulation measurements, not physical DDR throughput or inference measurements.
Board timing is checked separately; no 100 MHz claim follows from these results.

## Reproduction

```sh
python3 hardware/synapse32/experiments/dma/run.py stress \
  --out build-throughput-new --cpu-overlay-dir build-ddr-divider-payload/overlay \
  --system-mul --bus-payload --uart-control --dram-command-buffer \
  --dram-write-buffer --packed-rows --firmware-opt=-O3 \
  --shapes-file hardware/synapse32/experiments/dma/gemm_shapes.json
python3 tools/synapse32_tpu_utilization.py \
  --reference build-throughput-new --out build-util-throughput-new
```

Evidence: `build-ddr-gemm-throughput-{os,o2,o3,legacy}/system/results.json`,
`build-ddr-utilization-throughput-{o2,o3}/results.json`,
`build-ddr-dma-firmware-errors/results.json`, and
`build-ddr-firmware-throughput/{comparison,soc}/results.json`.
The prior source is saved at `build-ddr-firmware-throughput/dma_backend_before.c`.

## Board timing result

The selected `-O3` smoke firmware synthesizes and routes at the same diagnostic
timing as the prior packed-row build: **102.51 MHz CPU / 81.57 MHz system**,
system-to-CPU 8.62 ns and CPU-to-system 10.13 ns. The full 100 MHz target still
fails; the existing unsupported I/O-bank constraint diagnostic also remains.
No FPGA was programmed. Evidence:
`build-ddr-dma-throughput-o3/board/route-manifest.json`.
