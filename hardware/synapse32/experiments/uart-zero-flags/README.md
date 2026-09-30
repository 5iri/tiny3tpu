# UART baud zero flags — not selected

This opt-in `--uart-zero-flags` experiment registers each baud counter's zero
predicate on its existing update edge. Reset, initial state, decrement, full
reload and half-divisor reload mirror the original 16-bit counter exactly.
No counter width, baud interval or bus acceptance cycle changes.

`prove.py` proves the full UART module sequentially (489 comparison points),
including FIFO state, serial output, reads and interrupts under arbitrary bus,
RX and reset inputs. Separate identities cover every 16-bit decrement and
half-divisor value. The transform reverses to the exact original source.
The integration driver validates proof hashes and exact source/candidate bytes.

Smoke and all 45 GEMM shape records match the preceding DMA burst-limit
candidate exactly. Firmware and XDC are byte identical. Synthesis uses
625 CARRY4, 6,502 LUT6, 7,411 FDRE, 6,367 FDCE, 36 DSP48E1 and 16 RAMB36E1.

| Seed | PCOUT/carry = 0/0 ns | 1/0 ns | 0/0.1 ns |
|---|---:|---:|---:|
| 4 | 12.657 | 12.657 | 13.457 |
| 8 | 14.212 | 14.212 | 15.112 |

These are expanded timing sensitivity intervals in ns with symbolic missing
delays, not physical Fmax. Neither seed beats UART local acceptance seed 8
across the probes (12.510/12.510/12.710 ns), so this experiment is not selected.

Evidence: `build-uart-zero-flags-proved/{results,throughput-comparison,synthesis-comparison}.json`,
`build-ddr-dma-uart-zero-burst`, `build-ddr-gemm-uart-zero-burst`,
`build-ddr-seeds-uart-zero-burst-graph/seed-{4,8}`, and
`build-ddr-uart-zero-burst{4,8}-timing-sensitivity`.
