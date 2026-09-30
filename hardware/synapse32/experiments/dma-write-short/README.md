# Direct short-write burst detection

For the current 32-bit AXI engine, a nonempty transfer's first burst has one
beat when either its remaining length is 1..4 bytes, or the current address
is within the last four bytes of a 4 KiB page. The second case caps the burst
at the page boundary even when the descriptor has many bytes remaining.

This candidate derives the initial last-cycle flag from those inputs instead
of sending it through burst-size selection, count subtraction and zero testing.
It builds on [direct decrement flags](../dma-write-last/README.md). It retains
all actual count updates and the full AXI state machine; no cycle is added.

The specialization is guarded by the exact relevant profile: aligned engine,
16-bit length, AXI burst-size exponent 2, 15-bit cycle count, 32-bit address,
64-byte maximum burst and offset mask 3. Other profiles use the previously
proven expression. The range test is written using bit comparisons.

The formal harness copies the actual burst-selection code and compares its
stored 15-bit count against the new predicate. It covers all 16-bit remaining
lengths and all 32-bit addresses, including zero length, unaligned addresses,
and every 4 KiB boundary. No reachable-state assumption is used.
`build-dma-write-short-guarded/results.json` is the current passing proof;
the earlier `build-dma-write-short` snapshot predates the explicit offset-mask
guard and is not used by the driver.

`--dma-write-short` implies `--dma-write-last`, then applies this second
replacement. The driver verifies both proof manifests and exact intermediate
and final RTL bytes. Generated source selection remains explicit; the original
third-party RTL is unchanged.

The 27-case DMA/TPU unit test passes with 3,693 read beats, 3,685 write beats
and 16,345 cycles. Complete smoke and 45-shape PROFILE, METRICS and DMA
records remain identical to the atomic/boot baseline. The full diagnostic
retains 1,659,843 instructions, 2,084,686 enabled CPU edges and 11,544,608
system cycles. See `build-dma-write-short-guarded/throughput-comparison.json`.

Synthesis passes with 653 CARRY4s and 6,509 LUT6s. FDRE/FDCE, DSP and BRAM
counts, firmware and XDC bytes are unchanged from the preceding candidate.
The first two expanded diagnostic routes are:

| Symbolic carry / PCOUT delay | Previous retained candidate | Seed 4 | Seed 8 |
|---|---:|---:|---:|
| 0 / 0 ns | 13.961 ns | 15.774 ns | 13.855 ns |
| 0 / 1 ns | 13.961 ns | 15.774 ns | 13.855 ns |
| 0.1 / 0 ns | 14.661 ns | 16.874 ns | 14.735 ns |

These are the largest intervals, not physical Fmax. The longest endpoints
have moved to DMA write address bit 29 (seed 4) and the write-pending flag
(seed 8); the modified terminal flag is no longer the global maximum. Seed
4 CPU→system is 10.345 ns at zero substitutions, but its system paths regress.
The first pair does not establish a clear overall improvement across probes.
Evidence: `build-ddr-write-short4-timing-sensitivity/manifest.json` and
`build-ddr-write-short8-timing-sensitivity/manifest.json`.

Two additional placements do not improve the result:

| Symbolic carry / PCOUT delay | Seed 2 | Seed 7 |
|---|---:|---:|
| 0 / 0 ns | 15.230 ns | 15.620 ns |
| 0 / 1 ns | 15.230 ns | 15.620 ns |
| 0.1 / 0 ns | 16.030 ns | 16.420 ns |

Evidence: `build-ddr-seeds-write-short-more-graph`,
`build-ddr-write-short2-timing-sensitivity/manifest.json` and
`build-ddr-write-short7-timing-sensitivity/manifest.json`. No tested seed
improves on the retained candidate across all three probes. The two write
experiments stay optional. The retained atomic/boot candidate remains
13.961 ns at zero substitutions and 14.661 ns with 0.1 ns per missing carry
arc. Those diagnostics still miss the 10 ns target; neither establishes Fmax.

An additional proof, `build-dma-write-short-guarded/burst-bound-results.json`,
establishes that actual START burst selection is always 0..64 bytes for the
current profile and arbitrary inputs. Thus the selected burst value fits in
seven bits. This is a combinational range proof, **not** a completed register
width optimization or proof that the beat counters can be narrowed. A future
width change must preserve their underflow, assignment-width and output
semantics. The current RTL still retains all original counter widths.

```sh
python3 hardware/synapse32/experiments/dma-write-short/prove.py \
  --source build-dma-write-last/axi_dma_wr.v --out build-short-proof-new

python3 hardware/synapse32/experiments/dma/run.py system \
  --out build-dma-short-new --cpu-overlay-dir build-atomic-word-v2/overlay \
  --system-mul --bus-payload --uart-control --dram-command-buffer \
  --dram-write-buffer --packed-rows --firmware-opt=-O3 --tpu-counters \
  --csr-read-direct --dram-parallel-chooser --dma-read-compare \
  --uart-address-decode --boot-address-decode --dma-write-short
```

No board defaults are promoted. [Timing-model gaps](../core-timing/README.md)
still apply; the expanded model uses symbolic delays and cannot establish
physical Fmax or 100 MHz closure.
