# Parallel UART readback

Readback uses disjoint masked byte terms for register address, DLAB and RX
ownership instead of a nested index mux. All address-validity, enable and reset
gating remain. No state, FIFO, bus acceptance or response edge changes.

`build-uart-read-parallel-proved/results.json` proves full UART equivalence.
The proof composes with UART reset control, and `dma/run_uart_read.py` checks
exact candidate bytes and hashes. The tested CPU overlay also includes divider
sign selection. Complete smoke and all 45-shape PROFILE/METRICS/DMA records are
identical to the preceding workload; firmware and XDC remain unchanged.

Original-backend seeds 4/8 report 92.89/101.21 and 93.70/108.93 MHz system/CPU.
Expanded timing probes remain 12.945/12.945/13.483 and
13.577/13.577/13.977 ns, so this improves native reporting but does not replace
the UART reset-control candidate's best expanded comparison. Neither report
establishes whole-SoC physical Fmax or closes 100 MHz.

Evidence: `build-ddr-{dma,gemm}-uart-read-divsign`,
`build-ddr-seeds-uart-read-divsign-original-graph`, and
`build-ddr-uart-read-divsign-original{4,8}-timing-sensitivity`.
