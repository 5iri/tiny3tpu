# Capture Wishbone region selects with the address

The prior system-clock critical path starts at `wb_adr[29]`, passes through
board address decoding and native write-data readiness, and ends at a LiteDRAM
frontend state register: 12.26 ns, with about 10.7 ns in routing.

This opt-in experiment calculates the control/DDR region selects from `req_addr`
on the existing `req_valid && req_ready` capture edge. The bridge captures
`wb_adr` on the same edge. Reset clears both selects, matching the original
zero address. This removes the post-register address comparison from the
downstream enable path without adding a transaction or CPU cycle.

The exact candidate block is shared by the board transformer and proof harness.
Yosys temporal induction proves both select outputs equal the original bridge
decode on every cycle from reset-equivalent initialization, with arbitrary
request addresses, data, ready, ACK, ERR and repeated reset inputs. The proof
does not assume a well-behaved Wishbone slave. It checks selection equivalence,
not DDR electrical behavior or physical timing.

```sh
python3 hardware/synapse32/experiments/wb-decode/prove.py --out build-ddr-wb-decode
python3 hardware/synapse32/experiments/dma/run.py system --out build-decode-new \
  --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul --bus-payload \
  --uart-control --dram-command-buffer --dram-write-buffer --packed-rows \
  --firmware-opt=-O3 --wb-decode
```

Use the same options with `synth`, then `route`. Synthesis requires matching
proof-source hashes. The default board top and sibling CPU are not modified.
The behavioral CPU/DMA/TPU test retains exact PROFILE, METRICS and DMA records;
it does not instantiate the physical Wishbone frontend. The proof supplies
the cycle-equivalence check for the board-only change.

Evidence is in `build-ddr-wb-decode/results.json` and
`build-ddr-dma-wb-decode`. The completed seed-4 route is rejected: 99.59 MHz
CPU / 78.11 MHz system, with system-to-CPU 9.30 ns and CPU-to-system 10.15 ns.
The previous packed route remains better at 102.51 MHz CPU / 81.57 MHz system,
with CPU-to-system 10.13 ns. Neither closes the full 100 MHz target.

The candidate's system critical path now starts at
`memory.main_bankmachine2_trccon_ready` and ends at a register clock enable:
12.8 ns total, about 1.9 ns logic and 10.9 ns routing. Removing the address
decode did not improve overall routed timing. The experiment remains disabled
by default; formal equivalence and identical functional profiles are insufficient
grounds to adopt a physical timing regression. The unsupported `get_iobanks`
constraint warning also remains; these are diagnostic timing results, not DDR
hardware signoff.
