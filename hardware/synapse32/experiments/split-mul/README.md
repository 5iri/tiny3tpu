# Split cascade-free multiply — measured: cascade gone, CPU flat, SYS up

Replaces the ALU's three 64x64 products (deep DSP-cascade paths) with one
33x33 product split into four single-DSP 18x18 partials combined in fabric.
Each partial fits one DSP48E1 25x18 multiplier, so there is no ACOUT/ACIN or
P cascade on the MUL path. Composes the forwarding-retime overlay; MUL stays
single-cycle combinational, so instruction latency, stalls, traces and IPC
are unchanged. Production RTL and upstream Synapse32 are not modified.

Math: operands are sign/zero-extended to 33 bits per MUL variant (same rule
as `shared-mul`), split into unsigned 17-bit low and signed 16-bit high
limbs. All four partials are exact in 36-bit signed arithmetic; shifts are
constant rewiring; the 66-bit sum is exact because the true product fits in
64 bits. `MUL` uses `mul_product[31:0]`; high halves use `[63:32]`.

```sh
python3 hardware/synapse32/experiments/split-mul/run.py verify --out build-split-new \
  --ipc-baseline <forward-retime-out-dir>
python3 hardware/synapse32/experiments/split-mul/run.py synth --out build-split-new
python3 hardware/synapse32/experiments/split-mul/run.py route --out build-split-new \
  --nextpnr <nextpnr-xilinx> --chipdb <xc7k325tffg900-2.bin> --allow-const-holdouts
```

`verify` runs the 524,288-comparison Icarus ALU equivalence against the
forwarding-retime ALU, the CPU/collision/DRAM suites, and the fixed-MUL IPC
benchmark against the forwarding-retime baseline (identical trace and IPC
required). `route` returns failure when timing acceptance fails even if
nextpnr completes; output is rejected for bitstream use. Use a fresh `--out`
to preserve evidence.

## Measured (KC705 db built from source on ARM Mac, seeds 4/8)

| Clock | Forward-retime | + split-mul (s4) | + split-mul (s8) |
| --- | ---: | ---: | ---: |
| `soc.cpu_clk` / 100 | 47.53 FAIL | 47.38 FAIL | 46.80 FAIL |
| `clk` sys / 100 | 59.24 FAIL | 68.38 FAIL | 64.38 FAIL |
| cpu->clk cross / 10ns | 12.34 FAIL | 12.30 FAIL | 12.18 FAIL |

DSP 44 -> 36 (4 CPU + 32 TPU as designed); DSP cascade gone from the CPU
critical path (21.1ns = 3.2 logic + 17.9 routing through LUT/adder fabric).
Verification: 524,864 ALU comparisons bit-exact; CPU/collision/64-case suites
pass; DRAM workload 9294/8400/35 results; IPC 0.973045 identical both modes.
Seed 8 shows a marginal `iodelay_clk` 197.5/200 FAIL (placement noise).

Honest reading: the cascade removal is structurally confirmed but CPU Fmax
is flat within seed noise — the remaining path is routing-dominated LUT soup
(85% routing), so further multiplier surgery alone will not close it. SYS is
up ~5-9 MHz for real. Next CPU work must cut LUT depth/placement spread, not
DSP structure.
