# Atomic word input bypass

The DMA read-comparison seed-8 graph has a 15.520 ns CPU-to-system diagnostic
path ending at `req_wdata[11]`. Its origin is EX/MEM instruction ID bit 5. The
path traverses load-width selection, an atomic signed comparison, atomic/store
arbitration and byte-lane alignment. This interval uses symbolic zero carry
and DSP-cascade delays; it is not a validated physical delay or Fmax.

The CPU already forces LR/AMO reads to word width. This overlay feeds the
atomic LSU the four forwarded bytes before the ordinary load-width selector.
The byte forwarding itself remains intact, including pending store-buffer
contents. Byte/halfword load sign extension is unchanged for ordinary loads.
There is no new instruction, pipeline stage, memory transaction or bus cycle.

`prepare.py` copies the retained CPU overlay into a separate directory. It
changes only the atomic read-data connection and adds a combinational word
alias, with exact inverse-text checks. The original CPU and existing overlay
remain unchanged. A forward declaration keeps the Verilog frontend strict.

`prove.py` extracts the actual CPU merge logic and both atomic instances into
a proof harness and uses the real `atomic_lsu.v`. Temporal induction proves
all atomic outputs and reservation registers equal. Instruction IDs, memory
data, store-buffer contents/ownership, memory-unit outputs, reset and external
store notifications are arbitrary. No disabled-store-buffer, alignment or
RV32IM-only instruction assumption is used. Thus the proof covers atomic
instructions even though the GEMM firmware uses RV32IM.

Evidence: `build-atomic-word-v2/results.json` and `proof.log` (induction passes
at length 1). `throughput-comparison.json` compares every PROFILE, METRICS and
DMA field against DMA read comparison alone; all fields match exactly.

| Workload | Instructions | Enabled CPU cycles | System cycles |
|---|---:|---:|---:|
| Smoke | 106,588 | 142,895 | 789,205 |
| 45 shapes | 1,659,843 | 2,084,686 | 11,544,608 |

Standalone synthesis removes 105 LUT6s (6,480 to 6,375), with CARRY4, FDRE,
FDCE, DSP and BRAM counts unchanged. The combined UART-decode candidate has
6,451 LUT6s and 657 CARRY4s; placement/synthesis effects are not additive.
Both candidates retain exact firmware and XDC bytes. Synthesis comparisons
and the combined workload equality record are in `build-atomic-word-v2`.

The standalone expanded route results are:

| Symbolic carry / PCOUT delay | Seed 8 CPU→system | Seed 8 system→system | Seed 4 CPU→system | Seed 4 system→system |
|---|---:|---:|---:|---:|
| 0 / 0 ns | 11.505 ns | 19.251 ns | 12.070 ns | 17.603 ns |
| 0 / 1 ns | 11.505 ns | 19.251 ns | 12.070 ns | 17.603 ns |
| 0.1 / 0 ns | 11.705 ns | 19.551 ns | 12.170 ns | 18.003 ns |

The seed-8 CPU→system maximum improves from the DMA-only candidate's 15.520 ns,
but the overall worst interval regresses. UART RX FIFO count is the system
endpoint in both standalone routes. This motivates testing the combination
with UART decode; the standalone result is not a new overall timing winner.
Evidence: `build-ddr-seeds-atomic-word-graph`,
`build-ddr-atomic-word8-timing-sensitivity/manifest.json` and
`build-ddr-atomic-word4-timing-sensitivity/manifest.json`.

With UART address decode added, seed 8 CPU→system improves to 10.656 ns, but
boot RAM enable becomes the system maximum at 17.756 ns. Seed 4 reaches
12.582 ns CPU→system and 18.310 ns system→system. With 0.1 ns symbolic carry
arcs these become 10.956/17.956 ns and 12.582/18.510 ns, respectively. The
combined routes still do not beat the retained 15.520 ns overall diagnostic.
`build-ddr-atomic-uart8-timing-sensitivity/boot-traces.json` traces the seed-8
path from `req_addr[3]` through the general boot-range comparison to ENARDENU.
This motivates the [boot prefix decode](../boot-address-decode/README.md).

The first local proof build (`build-atomic-word`) failed frontend compilation
because the forwarded-byte names were declared after the instance. It is not
passing evidence; the validated candidate is `build-atomic-word-v2`.

```sh
python3 hardware/synapse32/experiments/atomic-word/prove.py \
  --source build-ddr-divider-payload/overlay --out build-atomic-word-new

python3 hardware/synapse32/experiments/dma/run.py system \
  --out build-dma-atomic-new --cpu-overlay-dir build-atomic-word-new/overlay \
  --system-mul --bus-payload --uart-control --dram-command-buffer \
  --dram-write-buffer --packed-rows --firmware-opt=-O3 --tpu-counters \
  --csr-read-direct --dram-parallel-chooser --dma-read-compare
```

Use matching arguments for synthesis after validation. No board default is
promoted. [Timing-model limitations](../core-timing/README.md) still prevent
a verified whole-SoC Fmax or 100 MHz signoff claim.
