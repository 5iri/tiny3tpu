# Exponential CORDIC

`tiny3tpu_cordic_exp.sv` implements binary32 exponential using a multiplier-free
hyperbolic shift/add CORDIC. Q3.29 range reduction subtracts ln(2), followed by
iterations 1 through 30 with repeats at 4 and 13. Output normalization rounds to
nearest, ties to even. The sampled 40,014-vector test observed at most 2 ULPs
error and 187 cycles latency. This is approximate math, not a rounding proof.

`tiny3tpu_cordic_mmio.sv` exposes control/status, input, output and identity at
offsets 0, 4, 8 and 12 from `0x20003000`. Full-word control bit 0 starts a
command; bit 1 clears completion/error. Status bits 0, 1 and 2 mean busy, done
and rejected overlapping start. Identity is `0x45585031`. The driver in
`include/tiny3tpu_cordic.h` checks identity and bounded completion, returning
failure without publishing outputs when hardware is unavailable or rejects work.

The compiler's `kc705-cordic` target places StableHLO exponential here. Build with
`--cordic`; existing board images do not acquire the peripheral automatically.
Sine, cosine, square root and division retain CPU lowering. Unit tests cover
special values, reset, backpressure, busy rejection and partial writes.
