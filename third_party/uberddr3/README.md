# UberDDR3 source snapshot

Selected, unmodified RTL from [AngeloJacobo/UberDDR3](https://github.com/AngeloJacobo/UberDDR3),
commit `79d8fd3e30ebba6acd84eecac2fa57b7f95f4544`, licensed GPL-3.0-or-later.
`UPSTREAM.json` records file hashes. The upstream license and copyright notices
are preserved. This snapshot does not include vendor simulation libraries or
proprietary tool scripts.

The KC705 build verifies these hashes, then writes a modified controller into
the build directory. Its manifest records each exact replacement:

1. Expose the existing BIST error/nonzero-correct counters in debug bits 31/30.
2. Decode masked writes per byte instead of using a variable part-select.
   Yosys SAT proves the replacement equivalent for arbitrary data and byte index.
3. End the alternating BIST phase after the final **read**, rather than its write.
   The controller-level regression checks the exact read/write counts and
   injects a fault into that final read.
4. Hold the final request through backpressure and wait for the expected number
   of checked reads before reporting completion.

The optional `--pipeline-bist` adaptation replaces the receiver with
`hardware/kc705_uberddr3/bist_receiver.vh`, comparing bytes in registers
before reducing their results. The manifest records the option and source hash.
`--onehot` asks Yosys to recode the calibration FSM; it does not edit the RTL.

The controller interface and PHY remain those of the pinned upstream version.
See [the KC705 trial](../../hardware/kc705_uberddr3/README.md) for build instructions
and the limits of the current validation.
