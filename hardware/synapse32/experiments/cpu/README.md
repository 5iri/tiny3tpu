# Track 2: isolated Synapse32 CPU combinational experiments

Only `csr_exec.v` is a candidate for a parent integration experiment.
No sibling source, production RTL, constraints, clocks, resets, or memory
protocols were edited. No route or FPGA programming was run by this track.

## Candidate and proof

`csr_exec.v` shares operand selection and set/clear/write Boolean planes.
The six instruction IDs are still compared exactly. Invalid IDs produce zero
write data and disabled writes. Register/immediate set and clear suppress writes
when rs1_addr is zero; write operations still write unconditionally. rd_value
always returns csr_read_data. The change is entirely combinational.

Run from any directory:

```sh
bash /Users/siriboi/github/tiny3tpu/hardware/synapse32/experiments/cpu/verify.sh
```

The script creates a unique /tmp build directory, runs serial Yosys jobs, caps
thread environment variables at two, and asserts combinational equivalence
against the read-only original. There are no FORMAL simplifications, input
assumptions, opcode restrictions, or latency changes. Yosys equiv_simple proved
all 65 CSR equivalence points and all 87 decoder points, including outputs and
matched internal nets. This is a two-state proof, not a four-state X-propagation
claim. XC7 mapping uses Slang, the production CPU frontend.

Verified tool: Yosys 0.63+173, 66306a8ca-dirty.
Evidence: /tmp/tiny3tpu-cpu-comb.UqCeBi/*.equiv.log, *.gold.log, *.gate.log,
and matching JSON files. Earlier classic-frontend exploration is in
/tmp/tiny3tpu-cpu-comb.UDy9fg and /tmp/tiny3tpu-cpu-comb.QFTtRl.

| Slang / synth_xilinx xc7 module mapping | Original | Candidate |
| --- | ---: | ---: |
| CSR LUTs | 41 | 44 |
| CSR CARRY4 | 2 | 0 |
| CSR INV | 4 | 0 |
| CSR MUXF7 | 0 | 9 |
| CSR longest cell path | 5 | 4 |
| Decoder LUTs | 152 | 149 |
| Decoder MUXF7 / MUXF8 | 25 / 6 | 48 / 12 |
| Decoder longest cell path | 7 | 9 |

The CSR result trades area/mux resources for lower topological depth. This is
not routed timing evidence: CARRY4 and LUT/mux levels have different delays,
and flattened whole-SoC mapping can change these results. Keep it experimental
until the parent's whole-design A/B comparison shows an actual benefit.

The decoder candidate in `rejected/decoder.v` bypasses generated imm[11:5]
when checking immediate shifts, using instr[31:25] in the I-type branch.
It is equivalent but rejected on the measured depth and mux regression.
An earlier parallel masked-OR immediate generator also regressed and was
removed. Do not integrate either decoder rewrite.

## Parent integration

In a unique /tmp synthesis script copied from the baseline flow, replace just
the source-list token
`/Users/siriboi/github/synapse32/rtl/core_modules/csr_exec.v`
with this directory's `csr_exec.v`. Do not include both definitions.
Leave every other CPU/board source and Slang option intact. The module name and
ports are drop-in compatible. Preserve the parent's clock, DDR, chipdb, seed,
and XDC settings for the comparison. Do not copy this directory wholesale into
the production core source list.

## Baseline findings

Inspected build-ddr/soc.json (45,670 top cells). Counting connected input pins,
the EX instruction-ID bus has a maximum per-bit fanout of 78; WB instruction-ID
106; CSR address / EX immediate 28; CSR write data 16. Clock/reset aliases are
excluded from these data/control figures (the reset alias reaches 9,433 pins).

The parent's completed diagnostic log is
`build-ddr/synapse-current-baseline.log`, nextpnr 52d3cc8, matched chipdb,
seed 4. Its final CPU clock report is 6.29 MHz against 100 MHz; system clock
39.97 MHz against 100 MHz. The CPU path at log lines 41067–41652 starts at
mem_wb_inst0_instr_id_out[0] and ends at ex_mem_inst0.exec_output_out[28].
It traverses `div_mod.div_mod_u.chaindata` (indices 191, 390, 519, 640,
841, 929, 1033): the actual dominant ALU hotspot is the unrolled combinational
divider, downstream of forwarding/writeback decode. Total reported delay is
159.0 ns: 27.8 ns logic and 131.2 ns routing.

This evidence does not justify expecting the CSR rewrite to close the CPU
clock. An iterative/pipelined divider would require latency/protocol work
outside this candidate's semantic constraints; no such change was made.
The diagnostic log reports timing FAIL despite zero tool errors, and its
unsupported get_iobanks / DCI handling remains a separate physical blocker.
No constraint removal, false path, ignored timing, or board-readiness claim
is part of this experiment.

## Original source SHA-256

```text
b3fb3c3210200928cbcbf7e9700a68f35039b795fe7ffdf544e2abc78a070c8b csr_exec.v
a3cc835029710ed96edb1b4c6b22f89318990611c5cdd4f9c21d3f8ae93a36a3 decoder.v
c547fb3ba283ecea39ce2ccbfba966f7d6af6b1c253e2694126e0a53b4bc07b0 alu.v
8a3c7cf00fcb454fcaa7963896b29ae2a05d251f6a0bf2685aff5339270856ae instr_defines.vh
```
