# Parent full-board divider-only experiment

Candidate: the four divider overlays, original CSR and boot decode.
Reproduce synthesis without modifying the upstream CPU:

```sh
.venv-ddr-compat/bin/python tools/kc705_open_build.py synth \
  --synapse32-dir /Users/siriboi/github/synapse32 \
  --cpu-overlay-dir hardware/synapse32/experiments/divider \
  --build-dir build-ddr-divider
```

Complete synthesis passed both final structural checks. `cmp` confirmed XDC
and firmware HEX identical to `build-ddr`. Boot RAM remains 16 RAMB36E1.
The experiment changes CPU instruction latency, not clock frequency.

Diagnostic routing used nextpnr 52d3cc8, its fresh matched
`/tmp/tiny3tpu-nextpnr-current/kc705.bin`, seed 4, `--freq 100`, and original
DCI XDC. Automatic clock derivation includes CPU/system 100 MHz, DDR 400 MHz,
input/IDELAY 200 MHz. No timing exception or ignored-failure flag was added.

| Final routed Fmax | Original | Divider-only |
| --- | ---: | ---: |
| CPU | 6.29 MHz | 41.81 MHz |
| System | 39.97 MHz | 61.02 MHz |

Both still FAIL at 100 MHz. This is not an application speedup claim: divide
instructions take more cycles. The route process returned zero despite timing
failures. Its unsupported DCI warning also remains. Nothing was programmed.

New CPU critical path: ID/EX rs1-valid control to EX/MEM execution output,
23.9 ns (3.1 ns logic, 20.8 ns routing), not the old unrolled divider chain.
New system path: sequencer state/address through peripheral decode,
16.4 ns (2.4 ns logic, 14.0 ns routing). Evidence: `build-ddr-divider/route.log`.

Parent reran `verify.sh`: 16,437 arithmetic checks; continuous and sequencer-
clocked actual-CPU tests each passed 1,067 divisions and 1,355 ordered stores.
The added CTest `synapse32_divider_dram` also passed the existing real-CPU
variable-latency memory-model -> AXIS -> TPU signed-GEMM workload. This test
uses RV32I firmware and does not replace the dedicated DIV instruction tests.

Parent verification also passed 128 directed CPU collision cases across
continuous and sequencer-gated clocks: 48 interrupt boundary cases and 80
instruction/load-fault launch cases, including 40 fault/IRQ priority collisions;
512 ordered stores were checked. Assertions verify boundary state, cancellation,
trap cause/resume PC, and exactly one successful divide retirement/writeback
after retry. Independent Astra review confirmed this coverage. Parent evidence:
`build.jF863M` and `/tmp/tiny3tpu-divider-collision-parent.log`.

Remaining coverage limits include independent elapsed-cycle checks, successful
retirement CSR increment, faulting-load writeback suppression before retry, and
additional reset/store-fault/simultaneous-fault combinations. These directed
fault-input tests do not validate an MMU. All 27 CTest regressions passed again,
including the JAX simulation path and divider memory-model-to-TPU test.

The separately routed divider-plus-bootdecode combination regressed to CPU
37.84 MHz / system 53.42 MHz at the same target and seed. Retain divider-only;
see `../combined/DIVIDER_BOOT_RESULTS.md` for evidence.

Board bring-up does not claim MMU/atomic support. Physical DDR calibration, external
IO and clock-enable timing, and full hardware acceptance remain unverified.
