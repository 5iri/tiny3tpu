# Boot address prefix decode

The CPU atomic-word and UART-decode combination exposes a boot RAM enable
path through the general range comparison: `req_addr[3]` to ENARDENU is
17.756 ns in the seed-8 graph with zero symbolic carry/cascade delays. The
trace is in `build-ddr-atomic-uart8-timing-sensitivity/boot-traces.json`.

For the current 16,384-word (64 KiB) boot memory, the address condition is
exactly `req_addr[31:16] == 16'h8000`. The candidate uses that prefix comparison
when BOOT_WORDS is 16384 and keeps the original expression for other sizes.
All byte offsets and the address map are preserved. The boot enable, index,
read/write state, reset and response timing do not change.

`build-boot-address-decode/results.json` proves exact decode equality for all
32-bit addresses and signed 32-bit BOOT_WORDS values. The harness copies the
actual old/new expressions, without alignment, handshake or state assumptions.
The generator verifies that reversing the one expression replacement recovers
the entire original SoC source.

The opt-in `--boot-address-decode` flag verifies current proof hashes before
applying the change. The existing system-source checks require this exact
generated SoC to have passed simulation before synthesis. The separate local
boot-enable experiment is not combined with this probe.

Smoke and 45-shape PROFILE, METRICS and DMA records match DMA read comparison
alone exactly (`build-boot-address-decode/throughput-comparison.json`). The
full diagnostic retains 1,659,843 instructions, 2,084,686 enabled CPU cycles
and 11,544,608 system cycles. Atomic-word and UART-decode proof hashes remain
current for this composition.

Synthesis passes with 653 CARRY4s and 6,436 LUT6s, versus 661 and 6,480 for
DMA read comparison alone. FDRE/FDCE, DSP and BRAM counts are unchanged.
Firmware and XDC bytes are identical, as recorded in
`build-boot-address-decode/synthesis-comparison.json`.

## Expanded route result

| Symbolic carry / PCOUT delay | Previous best DMA-only, seed 8 | Full combination, seed 4 | Full combination, seed 8 |
|---|---:|---:|---:|
| 0 / 0 ns | 15.520 ns | 13.961 ns | 15.751 ns |
| 0 / 1 ns | 15.520 ns | 13.961 ns | 15.751 ns |
| 0.1 / 0 ns | 15.720 ns | 14.661 ns | 16.551 ns |

The table reports the largest interval in each expanded diagnostic graph.
Seed 4 is a new best candidate in these three probes: approximately 10.0%
less delay at zero substitutions and 6.7% less in the 0.1 ns carry probe.
These are comparisons between the best tested placements, not physical Fmax
measurements or a claim of improvement at every possible unknown delay.

The seed-4 zero-substitution intervals are 13.961 ns system→system, 11.679 ns
CPU→system, 8.610 ns system→CPU and 10.531 ns CPU→CPU. Its longest endpoint is
`soc.dma.engine.axi_dma_wr_inst.output_last_cycle_reg`. Seed 8 instead ends at
the DMA read-pending flag. CPU and system paths still miss the 10 ns target.

The graph includes the four registered CPU DSPs, sixteen boot BRAMs, 2,603
observable RAMD32 outputs and 11,278 missing carry dependencies. Carry and
MREG-to-PCOUT delays remain symbolic; other primitive/clock validation gaps
also remain. In seed 4, a tracked cascade path already takes 10.440 ns with
zero PCOUT delay; its -0.440 ns remaining budget is a failure, not an estimate
of that unknown delay. Full timing acceptance remains false.

Evidence: `build-ddr-seeds-atomic-boot-graph`,
`build-ddr-atomic-boot4-timing-sensitivity/manifest.json` and
`build-ddr-atomic-boot8-timing-sensitivity/manifest.json`.
Raw native reports and the unsupported DDR I/O-bank/DCI warning are preserved.
The old incomplete native backend prints 80.31 MHz system for seed 4; this
omits carry paths and must not be interpreted as the whole-SoC Fmax.

```sh
python3 hardware/synapse32/experiments/boot-address-decode/prove.py \
  --soc build-ddr-dma-atomic-uart/synapse32_dram_soc.sv --out build-boot-decode-new

python3 hardware/synapse32/experiments/dma/run.py system \
  --out build-dma-boot-decode-new --cpu-overlay-dir build-atomic-word-v2/overlay \
  --system-mul --bus-payload --uart-control --dram-command-buffer \
  --dram-write-buffer --packed-rows --firmware-opt=-O3 --tpu-counters \
  --csr-read-direct --dram-parallel-chooser --dma-read-compare \
  --uart-address-decode --boot-address-decode
```

The driver uses proof evidence at `build-boot-address-decode/results.json`.
No board defaults are promoted. [Timing model limitations](../core-timing/README.md)
still apply: expanded symbolic-delay diagnostics do not establish physical
Fmax or 100 MHz closure.
