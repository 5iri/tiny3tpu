# UART address decode

The expanded timing graph of the DMA read-comparison candidate exposes a
15.184 ns system-clock path into the UART RX count. It traverses the UART's
general 32-bit inclusive address comparison before the FIFO control/count
logic. This is a diagnostic path with symbolic zero carry delays, not physical
timing signoff.

For a base aligned to 32 bytes, the candidate replaces that range comparison
with upper-bit equality and a check on the last three byte offsets. It still
accepts every original offset 0 through 28, including unaligned addresses,
and rejects offsets 29 through 31. Unaligned base configurations retain the
original expression. The top-level address map is unchanged.

`prove.py` extracts the exact old and new expressions into an unconstrained
SAT miter. All 32-bit addresses and base values are covered, with no address
alignment, handshake or reachable-state assumption. Only this assignment
changes in the already proven UART control overlay. No register, reset,
FIFO rule or cycle changes.

The opt-in `--uart-address-decode` flag implies the UART control overlay and
verifies proof hashes plus exact source/candidate bytes before use. Synthesis
also requires the exact candidate to have passed full-SoC simulation and
composes the address proof with the retained UART state proof.

Evidence in `build-uart-address-decode`:

- `results.json`: address-decode proof passes.
- `composition-check.json`: UART state proof hashes remain current; firmware
  and board constraint bytes exactly match the DMA read-comparison candidate.
- `throughput-comparison.json`: complete PROFILE, METRICS and DMA equality
  against the retained baseline for smoke and all 45 shapes.

| Workload | Instructions | Enabled CPU cycles | System cycles |
|---|---:|---:|---:|
| Smoke | 106,588 | 142,895 | 789,205 |
| 45 shapes | 1,659,843 | 2,084,686 | 11,544,608 |

Synthesis reduces CARRY4s from 661 to 657 and LUT6s from 6,480 to 6,455 relative
to DMA read comparison alone. FDRE/FDCE, DSP and BRAM counts remain unchanged.
Board synthesis: `build-ddr-dma-uart-decode/board/soc.json`.

## Route result — optional, not retained as the best candidate

| Unknown carry arc / PCOUT clock delay | DMA-only seed 8 | UART seed 8 | DMA-only seed 4 | UART seed 4 |
|---|---:|---:|---:|---:|
| 0 ns / 0 ns | 15.520 ns | 17.998 ns | 20.137 ns | 16.875 ns |
| 0 ns / 1 ns | 15.520 ns | 17.998 ns | 20.137 ns | 16.875 ns |
| 0.1 ns / 0 ns | 15.720 ns | 18.098 ns | 20.537 ns | 17.075 ns |

These are the largest intervals in the expanded diagnostic graph, not Fmax
or validated Kintex delays. The seed-4 comparison improves, but neither UART
route beats the best DMA-only result. Seed 8 regresses. The change therefore
remains optional; fewer carry cells do not by themselves establish a timing
improvement. In both UART routes the worst endpoint is in the memory sequencer.

Raw routes and unchanged constraints are in `build-ddr-seeds-uart-decode-graph`.
The full model/symbolic-delay records are
`build-ddr-uart-decode8-timing-sensitivity/manifest.json` and
`build-ddr-uart-decode4-timing-sensitivity/manifest.json`. They retain four CPU
DSPs, sixteen BRAMs, 2,603 used distributed-RAM outputs and 11,304 missing
carry dependencies; `full_soc_timing_accepted` remains false. The unsupported
DDR I/O-bank/DCI warning is preserved.

```sh
python3 hardware/synapse32/experiments/uart-address-decode/prove.py \
  --uart build-ddr-dma-read-compare/uart.v --out build-uart-address-decode-new

python3 hardware/synapse32/experiments/dma/run.py system \
  --out build-uart-decode-new --cpu-overlay-dir build-ddr-divider-payload/overlay \
  --system-mul --bus-payload --uart-control --dram-command-buffer \
  --dram-write-buffer --packed-rows --firmware-opt=-O3 --tpu-counters \
  --csr-read-direct --dram-parallel-chooser --dma-read-compare --uart-address-decode
```

Use the same flags for synthesis after current validation. The driver checks
the proof at `build-uart-address-decode/results.json`; a separately reproduced
proof does not silently replace that evidence. No board defaults are promoted.
See [core timing coverage](../core-timing/README.md) for why routed native MHz
values cannot establish whole-SoC Fmax or 100 MHz closure.
