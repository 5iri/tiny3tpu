> Superseded for current firmware by [FIRMWARE_THROUGHPUT.md](FIRMWARE_THROUGHPUT.md).
> The user subsequently prioritized useful work per total system cycle. Status
> scan removal is now retained with shorter result batches and a 45-shape audit.
> The measurements and rejection decision below describe the earlier experiment.

# Historical firmware completion-status experiment

The TDM1 hardware tracks nonzero command status words and AXI/protocol errors
in its aggregate completion ERROR bit. Firmware also scanned every status word
after DMA completion. Removing that scan reduces CPU instructions and external
DDR reads while preserving the data responses callers actually consume.

The DMA unit suite now checks command errors at the first, middle and last
positions of a 193-command batch, requiring ERROR at the first visible DONE.
All 27 tests pass, including the existing AXI errors, ownership, reset and final
write-response completion checks. All firmware candidates below pass 35 smoke
and 162 stress results with unchanged DMA beat/burst counts.

| Candidate | Smoke IPC | Smoke system cycles | Stress IPC | Stress system cycles |
|---|---:|---:|---:|---:|
| Existing inlined firmware, `-Os` | 0.775113 | 1,185,342 | 0.756835 | 2,189,877 |
| Remove redundant status scan, `-Os` | 0.774637 | 1,078,702 | 0.752206 | 1,832,828 |
| Same change, whole firmware `-O2` | 0.755587 | 911,236 | 0.787812 | 1,532,533 |
| Same change, only DMA backend `-O3` | 0.770608 | 1,034,216 | 0.739970 | 1,664,568 |

Each candidate reduces total cycles but lowers aggregate IPC on at least one
workload. Under the user's current strict IPC requirement, none is adopted.
`src/dma_backend.c` has been restored byte-for-byte to the existing inlined
baseline. This illustrates why IPC across different firmware instruction mixes
and useful GEMM throughput must be reported separately.

Exact source snapshots and the comparison manifest are in
`build-ddr-firmware-status`: `dma_backend_before.c`, `dma_backend_summary.c`,
`dma_backend_local_o3.c`, and `comparison.json`. Results are in the respective
`build-ddr-dma-status-summary`, `build-ddr-dma-status-o2`, and
`build-ddr-dma-status-local-o3` directories, with `-stress` companions.
No board timing result is claimed for these firmware variants.

The experiment runner now supports `--firmware-opt=-Os`, `-O2`, or `-O3`, with
`-Os` unchanged as the default. Simulation and board firmware use the same
selected optimization, and synthesis rejects validation from a different level.
