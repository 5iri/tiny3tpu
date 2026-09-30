# Stalling multiplier experiment — excluded for IPC regression

This diagnostic overlay captures multiply operands and computes four 16-bit
partial products through registered stages. It holds the CPU front end and
bubbles EX/MEM until completion. Each MUL adds five enabled CPU edges versus
the combinational multiplier. It must not be promoted under the user's IPC
requirement. Production CPU sources are unchanged.

The optional `--registered-divider` variant adds a divider operand setup cycle.
It also violates the current requirement to preserve instruction throughput on
the same workload; it was functionally tested but was not routed.

## Evidence

`build-ddr-mul` passed the arithmetic unit test (4,712 results plus cancellation
and reset boundaries), actual CPU MUL dependency/writeback tests, MUL exception
collision tests (84 cases per clock mode), original divider tests, and the
real-CPU DDR memory-model/TPU workload. Its seed-4 board route reached CPU
61.21 MHz and system 77.04 MHz, both below 100 MHz. Functional correctness and
frequency gains do not establish IPC preservation.

`build-ddr-ipc-benchmark/results.json` compares the identical no-interrupt,
no-fault program with the forwarding-retimed combinational-multiply baseline.
All ordered stores and multiply writebacks are checked, as is the complete
instruction-completion PC/opcode trace.

| Same instruction stream | Baseline | Stalling multiplier |
| --- | ---: | ---: |
| Completed instructions | 4,007 | 4,007 |
| Enabled CPU edges | 4,118 | 9,453 |
| CPU IPC | 0.973045 | 0.423887 |
| System cycles with sequencer gating | 49,516 | 93,348 |

Both continuous and gated clocks produce the same CPU IPC and identical
instruction traces. The regression is exactly 5,335 extra CPU edges for 1,067
multiply instructions. `benchmark.py` returns failure after preserving the
logs, hashes and comparison results when IPC drops or the traces differ.

The benchmark uses `instret_increment`, which resolves instructions in EX.
Interrupts and faults are prohibited and the pipeline is drained. This is
workload-specific IPC evidence, not precise architectural retirement validation
for exceptions or a measurement from the physical board. The RV32I DDR/TPU
firmware does not exercise hardware MUL, so its unchanged cycle count alone
cannot detect this regression.

```sh
python3 hardware/synapse32/experiments/mul-pipeline/benchmark.py \
  --baseline build-ddr-retime --candidate build-ddr-mul \
  --out build-ddr-ipc-benchmark-new
```

`build-ddr-mul-benchmark` retains the earlier cycle-only comparison. The newer
IPC run uses a separately hashed harness that also records completion traces.
