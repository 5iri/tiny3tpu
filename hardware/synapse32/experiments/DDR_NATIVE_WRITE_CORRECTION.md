# Native DDR write scheduling correction

The first registered-command-FIFO experiments had a protocol defect. With
depth zero, the COMMIT handshake completed when the write converter had
assembled the final chunk. After changing the FIFO to depth one, COMMIT
completed when metadata entered the FIFO, and the FSM issued a native write
command before its data was ready.

LiteDRAM's native crossbar does not wait for `wdata.valid`: the controller's
scheduled write phase consumes data and drives `wdata.ready`. The original
behavioral test waited for valid data and therefore hid this defect. Passing
those tests was insufficient to validate the changed native interface.

The new strict test schedules the write phase four cycles after accepting a
native command and requires data to be ready, without extending the deadline.
It passes the upstream adapter and fails the original buffered candidate on
its first native write, address 62, at both tested read-backpressure settings.
Evidence is in `build-ddr-native-upstream` and `build-ddr-native-buffered`.

The corrected generator adds WRITE-DRAIN after write metadata enqueue. Only
`wdata_finished` releases the FSM to CMD, restoring the original data-before-
command ordering. Read ordering retains its separate CMD-before-COMMIT flow.
Derived write-capture and two-entry-write-buffer generators inherit this
corrected adapter source instead of reconstructing the earlier patch.

Both corrected variants pass the strict test in
`build-ddr-native-buffered-fixed` and `build-ddr-native-write-buffer-fixed`.
The complete adapter suites now include this additional test. Board synthesis
requires passing strict-deadline evidence and matching current source hashes.

**Discard the earlier buffered-DDR routes as implementation candidates.**
This includes `build-ddr-dma-system-operands`, `build-ddr-dma-system-alu`,
`build-ddr-dma-system-control`, `build-ddr-dma-write-capture`,
`build-ddr-dma-system-csr`, `build-ddr-dma-uart-rx`, and the interrupted
`build-ddr-dma-system-decode` route. The earlier `build-ddr-dma-write-buffer`
netlist also predates the correction. Their logs remain historical diagnostic
evidence; their MHz numbers do not establish a working implementation. In
particular, the earlier 84.28 MHz CPU / 73.06 MHz system result is invalid as a
board candidate. Rebuild and route the corrected source before claiming gains.

CPU and firmware IPC measurements remain measurements of their stated
behavioral model. That model does not instantiate the LiteDRAM native adapter,
so it neither exercises this defect nor validates the correction's latency.
The CPU pipeline assertions and independent UART proofs are unaffected.

The corrected implementation has now been rebuilt and routed in
`build-ddr-dma-firmware-inline/board`. With seed 4 and the original constraints,
nextpnr reports **95.45 MHz CPU / 75.31 MHz system**. Related-clock paths measure
8.14 ns system-to-CPU and 9.54 ns CPU-to-system against 10 ns budgets. Both main
clocks still fail the 100 MHz target. The unsupported `get_iobanks` constraint
diagnostic also remains; this is diagnostic routing evidence, not DDR PHY,
calibration, clock-gating setup/hold or hardware signoff.

This build combines system-decode CPU staging, the corrected command adapter,
write capture, a two-entry completed-write FIFO, bus payload capture, UART RX/TX
payload reset separation, and inlined firmware command builders. All three
corrected DDR adapter suites pass 22 tests including the strict native write
deadline test. The firmware model passes all 35 smoke and 162 stress results;
as noted above, it does not simulate the native DDR frontend. Source hashes,
generation evidence, constraints, tool hashes and timing disposition are
recorded in `build-ddr-dma-firmware-inline/board/route-manifest.json`.
