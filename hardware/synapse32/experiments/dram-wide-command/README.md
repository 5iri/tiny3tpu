# Completed wide command queue — rejected

The opt-in `--dram-wide-command` candidate adds a two-entry FIFO between the
native upconverter's completed command and the DDR controller. It preserves
WRITE-DRAIN, the two-entry wide data buffer, and narrow-command coalescing.
This cuts downstream command-ready propagation, but can add command latency.
Installed LiteDRAM files are unchanged; generated source evidence is saved.

All 22 upstream/512-bit adapter tests pass, including strict native scheduled
write-data delivery, masked writes, bursts, unaligned accesses and immediate
read-after-write dependencies. A paired measurement of the strict 512-bit
workload shows identical traffic per scenario: 164 commands (67 writes / 97
reads), 67 write beats and 97 read beats. However, aggregate cycles rise from
7,731 to 7,881 (+1.94%). Scenario counts are 3,841→3,917 and 3,890→3,964.
This measures an adapter dependency workload, not full-system performance or
peak streaming bandwidth. No throughput-preservation claim follows from it.

CPU/DMA/TPU behavioral smoke retains 106,588 instructions, 142,895 CPU edges,
789,205 system cycles, and identical profiles/traffic. That test does not include
this physical DDR frontend and cannot measure the added command latency.
Synthesis passes. Matched seed routes regress:

| Seed | Baseline system / CPU MHz | Candidate system / CPU MHz |
|---|---:|---:|
| 4 | 81.57 / 102.51 | 79.20 / 98.67 |
| 7 | 81.14 / 102.43 | 79.28 / 93.76 |

The candidate is rejected: lower Fmax plus additional adapter cycles. It remains
disabled. Full 100 MHz closure and DDR physical signoff remain outstanding;
the I/O-bank warning persists. No timing exceptions were used.

Evidence: `build-ddr-wide-command/results.json`,
`build-ddr-wide-command/throughput-comparison.json`,
`build-ddr-dma-wide-command/system/results.json`,
`build-ddr-dma-wide-command/board/synth.log`, and
`build-ddr-seeds-wide-command/results.json`.

Use `.venv-ddr-compat/bin/python verify.py --out ... --upstream
/tmp/tiny3tpu-litedram-2024.12-tests` for adapter tests. `measure.py` uses the same
arguments, with `--candidate` for the queued variant; omitting it selects the
retained write-buffer adapter. In `dma/run.py`, use the retained packed/O3,
system-mul, bus-payload, uart-control, command/write-buffer options and add
`--dram-wide-command` for system/synthesis generation.
