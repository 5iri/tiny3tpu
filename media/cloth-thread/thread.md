# tiny3tpu progress thread

1/7 tiny3tpu now runs a compiled cloth simulation on a KC705 FPGA. Physics and state stay on the board: VexRiscv handles scalar math, the int8 TPU handles camera transforms. The host just generates pixels. Small mesh, real hardware.

Attach: 02-live-board.png
Alt: Actual rendered cloth capture from the KC705, with 28 vertices and a captured display rate of 5.4 FPS. This is not real-time simulation speed.

2/7 JAX is an offline frontend here. StableHLO is the compiler interface: export a tensor function, lower supported operations, then emit CPU code + TPU calls. Cloth is a test case; the compiler passes have no cloth-specific rules.

Attach: 01-architecture.png
Alt: StableHLO export flows through generic lowering and CPU/TPU placement to VexRiscv plus int8 TPU. Only geometry leaves the board for host rendering.

3/7 The first bottleneck was moving operands. In a first-step RTL benchmark at 100 MHz, packed transport cut 350.81 ms to 146.88 ms. Costed CPU/TPU placement brought it to 111.22 ms: 3.15× faster overall in that benchmark.

Attach: 03-transport.png
Alt: Three first-step RTL timing bars: scalar transport 350.81 ms, packed transport 146.88 ms, and packed transport with costed placement 111.22 ms.

4/7 “Put more on the TPU” wasn't automatically faster. Forced int8 affine offload lost to CPU placement once conversion + transport were included. The compiler needs to price the whole operation, not just count multiply-accumulates.

5/7 Validation matters: physical board outputs matched native generated C bit-for-bit across the tested requests—180 state words + 84 camera coordinates. That checks backend execution; it doesn't establish long-run agreement with JAX trajectories.

6/7 Next bottleneck: software float. ~85% of first-step RTL cycles were charged to multiply/add/divide/subtract, including stalls. Current VexRiscv has no FPU. An FPU + data cache is the next candidate to test, not a measured speedup yet.

Attach: 04-bottleneck.png
Alt: First-step cycle attribution: multiply 47.88%, add 20.37%, divide 9.79%, subtract 7.15%, other 14.81%.

7/7 Still experimental, still small. The goal is a generic compiler for supported tensor programs across the whole CPU + TPU system. Sources, tests, and bring-up notes are pushed. Working demo stays on VexRiscv for now.

https://github.com/5iri/tiny3tpu

## Measurement notes

Images are 1600×1000 PNGs. Board snapshot is captured data, not an FPGA photograph. The display rate varies with state and host rendering; each physics step advances only 1/7680 s. RTL timings are a separate first-step benchmark. Physical checks compare generated native C, not a proof of every StableHLO operation or full JAX numerical equivalence. Rocket's physical boot attempt failed and is documented separately.

Fresh release check: CMake build succeeded; all 34 configured CTest checks passed on 2026-09-30. Hardware demo validation was performed earlier and is documented in the compiler/cloth bring-up notes.
