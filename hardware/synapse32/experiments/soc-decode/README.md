# SoC boot prefix decode — measured: NEGATIVE result, direction abandoned

The cpu->clk cross path (12.3ns vs 10ns) runs EX/MEM instruction through the
`dram_soc` peripheral decode/procmux. Its deepest single term is the boot
range check (32-bit subtract + compare). For the production BOOT_WORDS=16384
geometry the condition is exactly `req_addr[31:16]==16'h8000`; other sizes
keep the original expression (Yosys folds the constant branch: CARRY4
550 -> 539, 0 problems). State elements, handshake and cycle behavior are
unchanged.

```sh
python3 hardware/synapse32/experiments/soc-decode/run.py prove --out build-soc-new
python3 hardware/synapse32/experiments/soc-decode/run.py verify --out build-soc-new \
  --cpu-overlay-dir <split-mul-overlay>
python3 hardware/synapse32/experiments/soc-decode/run.py synth --out build-soc-new \
  --cpu-overlay-dir <split-mul-overlay>
python3 hardware/synapse32/experiments/soc-decode/run.py route --out build-soc-new \
  --nextpnr <nextpnr-xilinx> --chipdb <xc7k325tffg900-2.bin> --allow-const-holdouts
```

`prove` checks the old/new decode for every high address half with boundary
low halves plus wrap corners. `verify` runs the CPU/collision/DRAM suites
(production SoC + CPU overlay); the proved combinational equivalence is what
transfers those results across the one-term delta. Needs the new
`kc705_open_build.py --system-overlay-dir` (named board-RTL replacement,
default build unaffected). `route` rejects output for bitstream use on any
timing/DCI failure. Use a fresh `--out` to preserve evidence.

## Measured (KC705 db, split-mul CPU overlay) — regression, do not select

| Clock | split-mul | + boot prefix (s4) | + boot prefix (s8) |
| --- | ---: | ---: | ---: |
| `soc.cpu_clk` / 100 | 47.38 / 46.80 | 46.96 | 41.93 |
| `clk` sys / 100 | 68.38 / 64.38 | 55.34 | 55.71 |
| cpu->clk cross / 10ns | 12.30 / 12.18 | 13.17 | 13.42 |

Verification held (393,222 decode checks; CPU/DRAM suites identical), but
both seeds regress ~9-13 MHz sys and ~1-5 cpu. The new sys limiter is
`sequencer.state -> procmux` at 2.2 logic + 15.9 routing: the smaller cone
placed worse. Lesson: in this routing-dominated regime (85-90% routing on
every failing path), isolated decode slimming perturbs placement more than
it saves logic. Abandoned; kept as negative evidence with proof + mechanism.
