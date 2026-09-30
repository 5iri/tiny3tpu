# Preserved-routing control

Direct rerouting of the final checkpoint fails: post-routing pin normalization
has added synthetic A6 ports to 5LUT cells. These ports have no physical router
sink. The correct rerouting entry point is before fixupRouting, not a guessed
cleanup of the final netlist. The failed control remains preserved.

An isolated backend hook captures a losslessly named checkpoint after routeVcc
and before fixupRouting. The hook reproduces the exact final routed JSON and
full raw timing graph; its pre-fixup checkpoint has equivalent logical ports.
See `build-grade2-pre-fixup-routing-control/iteration-integrity.json`.
The tool is archived at `build-toolchain-recovery/lossless-pre-fixup-tools.tar.gz`.

The full router can run on this unchanged pre-fixup checkpoint with imported
routes locked. Logical ports and BELs stay exact. Every non-ground route,
including clocks, stays exact. Ground gains 45 connections from the same
verified PSEUDO_GND driver and loses none. The timing graph has identical
rows including multiplicities, although serialization order changes.

The initial stricter all-route/byte-graph test remains marked failed.
`build-grade2-locked-pre-fixup-control/preservation-audit.json` separately
proves the narrower, explicit preservation contract. Its negative controls
reject changed signal routing, ground-route removal and a false ground value.
Do not describe the whole routing file as byte-identical.

Next: apply the already-proved write-address FF placement to this pre-fixup
checkpoint. Release all nets incident on the moved cells, preserve the other
routes, and run normal placement legality and routing. Check original state
and controls exactly, all retained physical endpoints, route preservation,
expanded probes and full integrity. No modified incremental design has yet
been tested, and no 100 MHz closure is claimed. Timing remains 10.318 ns.
