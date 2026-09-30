# Parent full-board forwarding experiment

The parent synthesized and routed the four-file forwarding overlay in
`build-ddr-forwarding`, using `overlay._6gb6s7_`. The copied RTL is recorded in
that overlay's manifest. Synthesis completed successfully. XDC and firmware HEX
compare byte-for-byte equal to `build-ddr-divider`.

Routing used nextpnr 52d3cc8 and its matched
`/tmp/tiny3tpu-nextpnr-current/kc705.bin`, seed 4, `--freq 100`, with the original
DCI constraints. CPU/system targets remain 100 MHz; DDR 400 MHz and input/IDELAY
200 MHz are unchanged. No timing exceptions were introduced.

| Final routed Fmax | Divider-only | Forwarding candidate |
| --- | ---: | ---: |
| CPU | 41.81 MHz | 41.99 MHz |
| System | 61.02 MHz | 48.02 MHz |

The CPU improvement is only 0.18 MHz in this single seed, while system timing
regresses by 13 MHz. Do not promote this as a general improvement. Retain the
divider-only integration as the working baseline and this candidate as an
isolated experiment. Both candidates fail the unchanged 100 MHz target.

Evidence: `build-ddr-forwarding/route.log`, final reports at lines 1938–1944.
The route process completed with exit zero, but the timing-report tool correctly
returned exit one and `accepted: false`, citing CPU/system timing failures and
unsupported `get_iobanks`/DCI. This is diagnostic timing, not DDR signoff.

The parent's actual-CPU memory-model-to-TPU test also passed: 9,294 reads,
8,400 writes, 35 signed results, and 4,981,249 system cycles. Test artifacts are
under `build-stream/synapse32-forwarding-dram`. This RV32I workload complements
the candidate's dedicated DIV and collision tests; it does not execute DIV.

No FPGA programming or physical DDR verification was performed.
