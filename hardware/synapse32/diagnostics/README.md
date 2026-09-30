# KC705 CPU isolation stages

For the 2026-09-26 investigation of nextpnr failing above 40 MHz, see
[the fresh synthesis/routing diagnosis](CLOCK_TIMING_DIAGNOSIS.md).

Stage 1 (`uart_loop.S`) initializes UART and repeatedly transmits U, with 16 RV32I instructions and no stack or DDR. Artifact directory: `build-kc705-cpu-stage1`. Simulation passed; physical SRAM programming passed, but 40 seconds of CP2103 capture received zero bytes. User observed LED0 on, LED2 on, LED7 blinking. This firmware never writes the DDR error CSR.

Stage 1a (`first_store.S`) writes zero to the existing completion register at 0x20002000, then loops. It should latch LED4 (finished) and LED5 (zero exit code). Simulation observes the completion write at cycle 38. Artifact directory: `build-kc705-cpu-stage1-led`. The SRAM image loaded successfully; the user reports LEDs 4 and 5 both off. Configuration STAT is 0x40107ffc (CRC clean, MMCM locked, initialization and DONE set). This stage fails on hardware. The image remains loaded for investigation.

Both images use `tools/kc705_patch_boot_fasm.py`. That tool verifies all 6386 original initialized words against routed RAM parameters and the original FASM, replaces only the boot RAM INIT data, reconstructs the full replacement 64 KiB image, and verifies every other FASM line is unchanged. Placement, routing, and clocks remain unchanged. Unused replacement boot space contains NOP instructions.

Stage 1 also passed bitstream-file frame decoding (excluding generated ECC words). This is file verification, not device memory readback. These diagnostic images do not establish DDR correctness or 100 MHz timing closure. No nonvolatile flash was programmed.

## Independent observer

`cpu_observer.sv` uses the retained CPU overlay/sequencer, a simplified synchronous boot RAM responder, a 100 MHz PLL output, and an independent hardware UART. Hardware received 17384 complete 16-byte packets with no skipped bytes: the first reported reset; all subsequent packets carried flags 0xbf, including CPU clock activity, instruction fetch, PC movement, and a write to 0x20002000. No fault flag appeared. PCs 0x80000008/0c/10 match the loop and pipeline fetch-ahead seen in simulation.

This is a fresh isolated route, not a repair or validation of the original full SoC. Local RAM response logic, reset stretching (65535 cycles), PLL output selection, and routing differ. Native nextpnr reports 111.45 MHz system and 102.93 MHz CPU for this diagnostic only; it is not full physical timing signoff. Artifact directory: `build-kc705-cpu-observer`.

Next comparison: the original routed completion test was reloaded successfully. A physical reset after configuration is pending. This tests restart behavior without rerouting, not controlled CPU reset duration: the button also resets the PLL, and the original system reset releases through a two-stage synchronizer after PLL lock. Both routed images place the CPU BUFGCTRL at X0Y16 with matching inversion parameters.

## Reset duration A/B test

The working observer was patched in exactly two LUT INIT features to change startup termination from count 65535 to count 2. All other FASM lines, placement, and routing remained identical. Matching RTL simulation passed. Hardware packets continued to report flags 0xbf (including successful completion write), with no fault. Artifacts: `build-kc705-cpu-observer-short-reset`. This excludes a need for the observer's long reset interval in this isolated implementation; it does not prove the full SoC reset distribution works.

## Original local-bus observer

The original boot RAM read/write block, boot-accept enable, local-boot response mux, bus handshake, and completion register were copied verbatim into the observer. Unused external/peripheral responses were stubbed; the three-instruction completion firmware does not access them. Both simulation and hardware passed. Hardware captured 17475 packets, all flags 0xbf, confirming the registered exit response with no fault. Twelve initial bytes were skipped to align to the packet header after capture was cleared at programming completion; four trailing bytes were incomplete. Artifact directory: `build-kc705-cpu-observer-localbus`. This uses a fresh route and does not prove the original packed implementation.
