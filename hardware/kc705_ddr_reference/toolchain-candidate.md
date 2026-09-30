# Isolated openXC7 candidate

Candidate checkout: `/tmp/tiny3tpu-nextpnr-current`, commit
`52d3cc889107db749e8d8ae93d3d50450a5d1979`.

Pinned submodules:

- nextpnr-xilinx-meta: `a4af910cac907f2cbd3a545f26f8e26573e860de`
- prjxray-db: `e8b8e8e46a91334f6232df84d36954323e15a1d1`

The installed `68aeeb3` binary is not replaced. Candidate source is unmodified.
Build uses CMake/Ninja, Release, `ARCH=xilinx`, `BUILD_GUI=OFF`,
`BUILD_PYTHON=OFF`, `USE_OPENMP=OFF` (Apple Clang rejects `-fopenmp`).
Python integration is unnecessary for the candidate's built-in clock propagation.

Regenerate the BBA using this checkout's `xilinx/python/bbaexport.py` and
assemble with its own `build/bbasm`; do not feed it an older chip database.

Source inspection confirms `propagate_clock_constraints()` runs in packing.
It also confirms settings-dictionary alpha/beta/criticality values are still
overwritten in `Arch::place()`. The effective environment overrides are
`NEXTPNR_PLACER_BETA`, `NEXTPNR_PLACER_ALPHA`, `NEXTPNR_SPREAD_SCALE_X`, and
`NEXTPNR_SPREAD_SCALE_Y`. Verify the logged effective values for each experiment.

Compare the same reference `classic.json`, XDC and seed 4, with fallback
`--freq 125`. Verify automatic clock derivation gives input 200 MHz,
system 125 MHz, DDR 500 MHz, and IDELAY 200 MHz. These checks are not physical
DDR timing signoff. No toolchain candidate or bitstream is approved for board
loading merely because compilation or routing exits successfully.

Astra source review confirms the old binary already has the same placement
environment overrides. Updating does not itself unlock new tuning controls.
The meaningful functional change under test is built-in clock propagation.
Propagation reports frequencies, not PLL phase relationships or complete
external-DDR timing. Expected PLL feedback frequency is 1000 MHz.

Candidate compilation succeeded with Apple Clang 21, Boost 1.90, Eigen 5.0.1;
`build/nextpnr-xilinx --version` reports `52d3cc8`.

## Completed comparison

Fresh `kc705.bba` generation and assembly to `kc705.bin` completed successfully.
The candidate automatically derives all expected buffered clock frequencies
from the original XDC; no manual Python clock overlay was used.

Same `classic.json`, seed 4, unchanged XDC, no timing exceptions:

| Tool/configuration | Final system Fmax | Target |
| --- | ---: | ---: |
| Installed 68aeeb3 + explicit clock overlay | 83.98 MHz | 125 MHz (FAIL) |
| Candidate 52d3cc8, default beta 0.4 | 75.30 MHz | 125 MHz (FAIL) |
| Candidate 52d3cc8, beta 0.6 | 71.58 MHz | 125 MHz (FAIL) |

Candidate logs are `current-default-route.log` and `current-dense-route.log`
in the reference checkout. Both processes exited zero despite final failures.
The logged effective beta values are 0.400 and 0.600, respectively.
These are toolchain-level comparisons, not an isolated clock-propagation
ablation: code and freshly generated chip database differ from the installed
baseline. The candidate fixes automatic constraint handling but does not close
timing or improve these routed results. Existing tools are left intact, and
none of these outputs was programmed.
