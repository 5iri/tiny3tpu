# Compare branches at the existing operand capture edge

The system-multiply CPU already captures both forwarded operands on each
system edge. This experiment captures equality, signed-less and unsigned-less
flags on that same edge, then uses them for the six branch conditions.
Reset sets flags to the comparisons of zero operands. The direct profile
retains combinational comparisons. No branch decision or CPU-enabled edge is
delayed; no prediction is introduced.

The invariant is that the three flags equal comparisons of `a_q/b_q` after
every system edge. `build-branch-compare-v2/results.json` proves this with a
universal one-step transition check and arbitrary operands/reset/previous
state. The registers are overwritten unconditionally each edge, so the
one-step relation applies at every edge without assuming initial values.
The direct profile is proven combinationally. The exact capture block is
shared by the generated CPU and proof harness. Only the six branch-condition
expressions change elsewhere in `execution_unit.v`.

The parent [shared branch case](../branch-select/README.md) proof is
`build-branch-select-base/results.json`; this variant uses the retained atomic
implementation, not the slower atomic-select experiment. The first proof
attempt in `build-branch-compare` failed because Yosys disallows combining
`-prove-skip` with `-tempinduct`; it is not passing evidence. The v2 proof uses
the correct one-step check described above.

Complete smoke and 45-shape PROFILE, METRICS and DMA records match the prior
baseline exactly: `build-branch-compare-v2/throughput-comparison.json`.
Full workload: 1,659,843 instructions, 2,084,686 enabled CPU edges,
11,544,608 system cycles. RTL phase balancing has not changed IPC or throughput.
Routing still determines whether this is a useful timing candidate.

The same flag-capture change is also proved and tested on the original branch
case, independently of branch-select: `build-branch-compare-original`.
That version also preserves every smoke/45-shape profile field exactly.

With the shared branch case, synthesis uses 625 CARRY4, 6,578 LUT6,
7,413 FDRE, 6,366 FDCE, 36 DSP48E1 and 16 RAMB36E1. Its expanded seed-4
probes are 13.267/13.267/13.467 ns and seed 8 is 13.631/13.631/13.831 ns
(PCOUT/carry 0/0, 1/0, 0/0.1). The worst endpoint moves to UART
`rx_fifo_count[4]`. Neither beats retained DMA-capacity seed 4, so this
combination is unselected. Evidence: `build-branch-compare-v2/route-integrity.json`.

With the original branch case, synthesis uses 627 CARRY4, 6,419 LUT6,
7,413 FDRE, 6,366 FDCE, 36 DSP48E1 and 16 RAMB36E1. Both variants keep
firmware and constraints byte exact; each has its own synthesis comparison
manifest.

The original-case version also fails to improve the selected candidate:
seed 4 gives 13.115/13.115/14.091 ns, seed 8 gives 14.220/14.220/14.920 ns.
Evidence: `build-branch-compare-original/route-integrity.json`. Both flag-capture
variants remain optional, with no default or selected-candidate promotion.
