# Register-file reset ownership — standalone timing regresses; combined probe underway

The CPU register file reset all 32×32 payload bits. This opt-in
`--registerfile-valid` candidate clears one written bit per register instead.
Unwritten registers read zero; a write marks its register written. Payload
storage has a synchronous write and no reset. A payload write during reset
cannot become visible because ownership remains cleared. Both read ports keep
the exact existing write-through forwarding rules, including behavior during
reset; x0 remains zero. The sibling CPU checkout is unchanged. The generated
SoC/board build replaces only registerfile.v in an isolated build directory.

Temporal induction proves both read outputs and every architectural register
value equal for arbitrary read/write addresses, valid bits, write data, write
enables and reset inputs. The invariant relates each original word to candidate
payload masked by written ownership. Evidence:
`build-registerfile-valid/results.json`. This is digital functional equivalence,
not physical RAM/clock/reset signoff.

Full-system smoke and all 45 GEMM shapes preserve exact PROFILE, METRICS and DMA
records: 3,022 checked GEMM results, full diagnostic 11,544,608 system cycles.
There is no added CPU edge, instruction or system cycle in these tests.
Evidence: `build-ddr-dma-registerfile-valid/system/results.json`,
`build-ddr-gemm-registerfile-valid/system/results.json`.

Synthesis passes and infers distributed RAM. Compared with the retained netlist,
FDCE count falls from 6,482 to 5,490 (992 fewer); RAM32M rises from 447 to 459;
LUT6 falls from 6,519 to 5,992. Standalone seed 4 reaches 79.05 MHz system / 97.28 MHz CPU; seed 7 reaches
76.12 / 101.34 MHz. Both system results regress against the same baseline seeds,
so the standalone candidate is not retained. Evidence is in
`build-ddr-seeds-registerfile-valid` and `build-ddr-seeds-registerfile-valid-7`.
A combined probe with narrow TPU counters is being measured separately; no
100 MHz closure is claimed. Unsupported I/O-bank constraints and
DDR physical signoff remain outstanding.

Use `prove.py --out build-registerfile-valid` to reproduce the proof. In the DMA
runner, use retained packed/O3, system-mul, bus-payload, uart-control and corrected
DDR command/write-buffer options, adding `--registerfile-valid`. A full shape
sweep uses stress mode and `--shapes-file .../dma/gemm_shapes.json`.

## Combined counter/register-file probe

The combined smoke and 45-shape suite retain exact baseline profiles. Synthesis
passes. First routes: seed 4 gives 79.96 MHz system / 98.80 MHz CPU; seed 7 gives
84.08 / 82.80 MHz. These do not beat the counter-only front-runner's joint
timing. The matched eight-seed comparison is now complete; see below. Evidence: `build-ddr-dma-counter-regfile`,
`build-ddr-gemm-counter-regfile`, `build-ddr-seeds-counter-regfile`, and
`build-ddr-seeds-counter-regfile-rest`.

## Completed combined eight-seed sweep

| Seed | System MHz | CPU MHz |
|---|---:|---:|
| 1 | 77.71 | 104.91 |
| 2 | 84.48 | 90.19 |
| 3 | 81.65 | 104.34 |
| 4 | 79.96 | 98.80 |
| 5 | 83.38 | 101.88 |
| 6 | 85.41 | 93.34 |
| 7 | 84.08 | 82.80 |
| 8 | 80.43 | 88.28 |

Combined system mean is 82.1375 MHz, versus 77.54125 MHz for counter-only over the same seeds. Combined best is 85.41 MHz, slightly below counter-only best 85.82 MHz. The combined design is a useful area/placement candidate, but does not improve the best available joint timing or close 100 MHz. Both retain exact workload profiles.
