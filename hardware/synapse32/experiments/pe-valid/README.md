# Reset ownership for PE accumulator payload

The PE keeps its architectural accumulator output asynchronously reset to zero.
A one-bit asynchronous validity register masks an unowned accumulator payload;
on the first edge after reset the feedback is zero, so the first product is
still accumulated on exactly the original edge. Signed feedback width is
explicit. Clear, A/B forwarding, accumulation and overflow behavior are unchanged.
The payload register itself has no asynchronous reset.

`build-pe-valid/results.json` proves DW=8/CW=32 output cycle equivalence for
arbitrary operands, clear and reset after reset initialization. The generated
candidate is isolated; `systolic_array/rtl/pe.v` remains unchanged.

Standalone Xilinx mapping changes the accumulator from fabric registers to the
DSP48E1 internal PREG, preserving the existing MAC latency. Per PE, FDCE count
falls from 48 to 17; DSP count remains one and LUT2 count remains 32. PREG changes
from zero to one. The remaining validity register provides asynchronous reset
semantics at the output.

`build-pe-valid/mapped-results.json` records 204,138 comparisons between the
mapped DSP primitive model and original RTL: randomized signed products, clear,
reset pulses entirely between clock edges, and a long signed-overflow sequence.
The testbench is [mapped_tb.v](mapped_tb.v). This is a digital primitive-model
check, not physical FPGA signoff.

The full-SoC smoke PROFILE, METRICS and DMA records match the selector baseline
exactly in `build-ddr-dma-pe-valid/system/results.json`. The 45-shape workload
also matches exactly in `build-ddr-gemm-pe-valid/system/results.json`.
Whole-chip synthesis maps all 32 PE accumulators to PREG and removes 1,023 FDCEs.

No routed timing gain is claimed: the baseline timing model ignores PREG DSPs,
and also ignores the four existing registered CPU DSPs. Initial stricter-model
trials fail explicitly on unsupported profiles. These are model coverage
failures, not design timing failures or valid Fmax measurements.
