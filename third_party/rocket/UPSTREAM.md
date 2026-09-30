# Rocket RV64GC

Generated LiteX `linux_1_1` core from `litex-hub/pythondata-cpu-rocket`, revision
`d641037640637471e82646e69a055475cd2abfab`. The package records Rocket revision
`4f197707e`. All imported files and their SHA-256 hashes are recorded in
`source-manifest.json`; the build checks those hashes before synthesis.

The RTL is unmodified. It includes one RV64IMAFDC core, FP32/FP64 FPU with
hardware division/square root, 16 KiB instruction and data caches, internal
boot ROM, CLINT, PLIC, and debug logic. The `linux` name describes the generated
configuration; this project runs bare-metal firmware, without an OS or DDR.

The external reset trampoline starts at `0x10000000`. Cached memory uses the
64-bit AXI port at `0x80000000`; the second 64-bit AXI port serves uncached MMIO
below that address. `hardware/kc705_rocket` adapts these ports to the existing
32-bit RAM and peripheral map. The unused inbound AXI and debug ports are tied
off. The original source licenses are preserved alongside the generated RTL.
