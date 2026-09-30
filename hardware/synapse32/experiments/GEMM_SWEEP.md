# GEMM shape sweep: legacy versus packed rows

45 distinct M×K×N shapes, one call each. Only GEMM calls are counted; boot,
input generation and caller result verification are excluded. All results were
checked by firmware and the independent host scoreboard before measurement.

| GEMM-scoped metric | Legacy | Packed |
|---|---:|---:|
| Completed instructions | 4,650,330 | 2,806,419 |
| Enabled CPU cycles | 5,723,712 | 3,420,601 |
| Pooled IPC | 0.812468 | 0.820446 |
| Equal-shape mean IPC | 0.792186 | 0.784306 |
| System cycles | 32,685,897 | 18,677,625 |
| Useful PE capacity | 0.006905% | 0.012084% |

Packed rows reduce total GEMM cycles by 42.86%.
IPC improves on 12 of 45 shapes; all 45 calls finish sooner.

Pooled IPC is `sum(instructions) / sum(enabled CPU cycles)`. It is the actual
ratio for this suite and equals a CPU-cycle-weighted mean of the shape IPCs.
An arithmetic mean gives each shape equal influence but is a different statistic.
For a deployment with repeat counts `w`, use `sum(w*instructions)/sum(w*cycles)`.

This is a representative synthetic sweep, not every possible GEMM or a measured
production workload distribution. It covers small matrices, dimensions around
4×4/8-wide tile boundaries, square matrices, long K, vector-like cases, tall/wide
matrices and padded tails. Memory is behavioral, with no physical DDR contention.

| M×K×N | Legacy IPC | Packed IPC | Legacy system cycles | Packed system cycles | Cycle reduction |
|---|---:|---:|---:|---:|---:|
| 1×1×1 | 0.743355 | 0.680369 | 31,014 | 12,029 | 61.21% |
| 2×2×2 | 0.758359 | 0.721197 | 36,137 | 17,355 | 51.97% |
| 3×3×3 | 0.775935 | 0.756730 | 44,114 | 25,836 | 41.43% |
| 3×7×3 | 0.779853 | 0.762432 | 45,163 | 26,091 | 42.23% |
| 3×7×4 | 0.789273 | 0.781074 | 49,735 | 29,665 | 40.35% |
| 3×7×5 | 0.775952 | 0.756872 | 84,313 | 45,826 | 45.65% |
| 3×8×3 | 0.781246 | 0.764926 | 45,266 | 26,076 | 42.39% |
| 3×8×4 | 0.790037 | 0.784398 | 49,905 | 28,995 | 41.90% |
| 3×8×5 | 0.776924 | 0.760078 | 85,216 | 44,863 | 47.35% |
| 3×9×3 | 0.793735 | 0.784547 | 83,126 | 44,312 | 46.69% |
| 3×9×4 | 0.801809 | 0.800803 | 90,635 | 51,860 | 42.78% |
| 3×9×5 | 0.790261 | 0.780465 | 154,371 | 76,704 | 50.31% |
| 4×7×3 | 0.786800 | 0.774364 | 50,384 | 31,159 | 38.16% |
| 4×7×4 | 0.796465 | 0.793023 | 56,382 | 35,785 | 36.53% |
| 4×7×5 | 0.782720 | 0.769539 | 92,939 | 53,462 | 42.48% |
| 4×8×3 | 0.788045 | 0.777759 | 50,416 | 30,683 | 39.14% |
| 4×8×4 | 0.797431 | 0.796620 | 56,162 | 35,386 | 36.99% |
| 4×8×5 | 0.783638 | 0.773498 | 93,331 | 53,012 | 43.20% |
| 4×9×3 | 0.799192 | 0.793514 | 92,124 | 53,753 | 41.65% |
| 4×9×4 | 0.807572 | 0.809640 | 102,910 | 63,674 | 38.13% |
| 4×9×5 | 0.795701 | 0.789824 | 170,635 | 92,830 | 45.60% |
| 5×7×3 | 0.774880 | 0.752115 | 84,422 | 46,504 | 44.91% |
| 5×7×4 | 0.783384 | 0.771324 | 92,183 | 52,208 | 43.36% |
| 5×7×5 | 0.771142 | 0.746895 | 159,634 | 81,571 | 48.90% |
| 5×8×3 | 0.776244 | 0.754307 | 84,826 | 46,044 | 45.72% |
| 5×8×4 | 0.784758 | 0.774409 | 92,612 | 51,720 | 44.15% |
| 5×8×5 | 0.772086 | 0.749779 | 160,678 | 80,319 | 50.01% |
| 5×9×3 | 0.789844 | 0.776222 | 154,312 | 78,292 | 49.26% |
| 5×9×4 | 0.797036 | 0.793541 | 168,423 | 90,014 | 46.55% |
| 5×9×5 | 0.786541 | 0.772437 | 291,640 | 136,762 | 53.11% |
| 8×16×8 | 0.810854 | 0.817277 | 418,782 | 252,803 | 39.63% |
| 16×16×16 | 0.810901 | 0.817231 | 1,671,850 | 1,010,290 | 39.57% |
| 32×32×32 | 0.818657 | 0.830304 | 12,965,965 | 7,662,092 | 40.91% |
| 4×64×4 | 0.822908 | 0.837530 | 399,496 | 234,054 | 41.41% |
| 8×128×8 | 0.824877 | 0.841278 | 3,167,883 | 1,841,812 | 41.86% |
| 4×256×4 | 0.826067 | 0.843323 | 1,577,315 | 915,935 | 41.93% |
| 1×64×16 | 0.802795 | 0.807155 | 1,007,457 | 362,844 | 63.98% |
| 16×64×1 | 0.799065 | 0.799407 | 1,039,517 | 398,690 | 61.65% |
| 32×8×4 | 0.796895 | 0.795358 | 443,740 | 279,027 | 37.12% |
| 4×8×32 | 0.797240 | 0.795615 | 442,894 | 278,001 | 37.23% |
| 64×16×4 | 0.810753 | 0.817080 | 1,671,317 | 1,009,764 | 39.58% |
| 4×16×64 | 0.810911 | 0.817248 | 1,673,019 | 1,008,868 | 39.70% |
| 7×13×9 | 0.799431 | 0.797797 | 522,577 | 283,960 | 45.66% |
| 3×5×6 | 0.778203 | 0.761679 | 88,376 | 49,468 | 44.03% |
| 15×17×17 | 0.808588 | 0.812769 | 2,742,701 | 1,547,227 | 43.59% |

Source measurements:

- [build-ddr-utilization-sweep-legacy](/Users/siriboi/github/tiny3tpu/build-ddr-utilization-sweep-legacy/results.json)
- [build-ddr-utilization-sweep-packed](/Users/siriboi/github/tiny3tpu/build-ddr-utilization-sweep-packed/results.json)

## Reproduction

The 45 shapes are in `hardware/synapse32/experiments/dma/gemm_shapes.json`.
Both paths pass 3,022 independently checked signed results.

```sh
python3 hardware/synapse32/experiments/dma/run.py stress --out build-sweep-legacy-new --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul --bus-payload --uart-control --dram-command-buffer --dram-write-buffer --shapes-file hardware/synapse32/experiments/dma/gemm_shapes.json
python3 hardware/synapse32/experiments/dma/run.py stress --out build-sweep-packed-new --cpu-overlay-dir build-ddr-divider-payload/overlay --system-mul --bus-payload --uart-control --dram-command-buffer --dram-write-buffer --packed-rows --shapes-file hardware/synapse32/experiments/dma/gemm_shapes.json
python3 tools/synapse32_tpu_utilization.py --reference build-sweep-legacy-new --out build-util-sweep-legacy-new
python3 tools/synapse32_tpu_utilization.py --reference build-sweep-packed-new --out build-util-sweep-packed-new
python3 tools/synapse32_gemm_compare.py --baseline build-util-sweep-legacy-new/results.json --candidate build-util-sweep-packed-new/results.json --out build-sweep-comparison-new
```

The full-program IPC, including boot, input generation and caller verification,
is 0.754244 legacy and 0.733208 packed. That is a different measurement window
from pooled GEMM IPC above. The packed firmware remains opt-in: pooled GEMM IPC
improves, but per-shape and equal-shape results expose regressions that the
pooled ratio alone does not show. The default firmware preserves earlier profiles.
