# Synapse32 placement/locality experiment

Scope: only experiments in this directory and private `/tmp` outputs. No RTL,
CPU sibling sources, clocks, reset, instruction/CSR behavior, DDR width/capacity,
or latency protocols are modified. No FPGA programming. The original XDC is
passed unchanged. These are diagnostic experiments: the supplied tool warns
that `get_iobanks` is unsupported, so DCI_CASCADE is not proven implemented.

## Reproduce

From the repository root:

```sh
python3 hardware/synapse32/experiments/placement/analyze.py \
  --netlist build-ddr/soc.json --log build-ddr/synapse-current-baseline.log
python3 hardware/synapse32/experiments/placement/run.py \
  --netlist build-ddr/soc.json --xdc build-ddr/kc705.xdc \
  --variant density060 --parent-log build-ddr/synapse-current-baseline.log
```

The runner allocates a unique `/tmp/synapse32-placement-*` directory, records
the exact command, environment and SHA-256 of input JSON, XDC, executable and
chipdb, and checks that those inputs did not change. It clears inherited
`NEXTPNR_*` overrides. Seed 4, HeAP, sys 100 MHz and all original XDC constraints
are used. Default mode is placement only. `density080` is a second available
probe, not a tested recommendation. There are no timing-ignore/force options.

## Available interfaces and candidate rationale

Inspected tool source `/tmp/tiny3tpu-nextpnr-current`, version `52d3cc8`:

- `common/arch_pybindings_shared.h`: `createRectangularRegion(name,x0,y0,x1,y1)`
  and `constrainCellToRegion(cell,region)` exist. `common/nextpnr.cc` creates
  inclusive tile-coordinate rectangles restricting BELs, not wires or PIPs.
  HeAP handles them in `common/placer_heap.cc`.
- This executable has `BUILD_PYTHON=OFF` / `NO_PYTHON` and exposes no `--pre-place`
  hook. Xilinx XDC parsing exposes no pblock/region commands. Do not pass Vivado
  pblock syntax and assume it worked. `NEXTPNR_FRESH_REGION_MARGIN` requires a
  pre-existing stamped BEL bounding box and targets all unstamped fabric;
  it is not a CPU-region selector for this design.
- `xilinx/arch.cc` implements `NEXTPNR_PLACER_BETA` (default .4),
  `NEXTPNR_SPREAD_SCALE_X/Y` (2/1), and `NEXTPNR_PLACER_ALPHA` (.08).
  Raising beta permits denser occupancy before spreading. Candidate .6 keeps
  all other placement knobs fixed and tests whether the CPU path benefits
  from less spreading. This is a global locality knob, not a hard CPU region.
- `--placer-budgets` is advertised, but is not selected: this experiment
  changes one placement parameter at a time.

The synthesized top has 45,670 cells, 2,109 FFs clocked by `soc.cpu_clk`, and
326 `soc.cpu.*` net aliases. Backward tracing CPU FF D/CE cones through LUTs,
MUXFs, carries and inverters identifies 22,346 cells, including the FFs.
This is a connectivity cone, not exclusive ownership; shared logic can occur.
ABC and FF cell names mostly lose CPU hierarchy. A `soc.cpu*` cell-name filter
would miss the actual logic and is unsuitable for a hard region.

The parent baseline's routed CPU critical path has 194 arcs, 27.8 ns logic,
131.2 ns routing, and tile bounding box `(76,263)`–`(144,340)`, with cumulative
Manhattan distance 1,915 tiles. It starts at `$auto$ff.cc:337:slice$98645.Q`,
net `soc.cpu.mem_wb_inst0_instr_id_out[0]`, and ends at
`$auto$ff.cc:337:slice$97456.D`. Internal nets include
`$auto$share.cc:669:make_supercell$46031.div_mod.div_mod_u.chaindata[1033]`.
Routing dominates this path, but its logic delay alone exceeds 10 ns.

## Two-worker routing build

The supplied router2 starts four quadrant workers without a cap; OMP thread
environment variables do not limit those `std::thread`s. HeAP has one x-axis
worker plus the main y-axis solver. To obey the two-worker constraint, the
experiment uses a private copy of `common/router2.cc`. Immediately after
`threads.emplace_back(...)` inside the `for (int i = 0; i < Nq; i++)` loop,
the only source addition is:

```cpp
// Preserve all four partitions and RNG contexts; run two at a time.
if (threads.size() == 2) {
    for (auto &t : threads)
        t.join();
    threads.clear();
}
```

Copy the original router2.cc to a unique directory from `mktemp -d /tmp/synapse32-placement-tool-XXXXXX`
and make that addition with `apply_patch`. Then compile and relink using the
existing build's exact Ninja commands and read-only objects:

```sh
python3 hardware/synapse32/experiments/placement/relink.py \
  --build /tmp/tiny3tpu-nextpnr-current/build \
  --router-source /tmp/YOUR-PRIVATE-TOOL-DIRECTORY/router2.cc
python3 hardware/synapse32/experiments/placement/run.py \
  --netlist build-ddr/soc.json --xdc build-ddr/kc705.xdc \
  --variant density060 --parent-log build-ddr/synapse-current-baseline.log \
  --nextpnr /tmp/YOUR-PRIVATE-TOOL-DIRECTORY/nextpnr-xilinx --route
```

Only one compiler or linker runs at a time; only one route is launched at a
time. The private executable uses the same matched chipdb, partitions and RNG
contexts. The scheduling change is an experimental confound versus the parent
baseline; improvement cannot be attributed solely to beta without a controlled
baseline using this same executable. The parent baseline is not duplicated.

## Interpreting evidence

Use the final routed critical-path/Fmax block, not the earlier placement Fmax.
For placement-only runs, `report.json` is after post-placement legalisation;
the earlier log Fmax is before that repair. This tool's JSON `critical_paths`
array is always empty by implementation; `analyze.py --log` extracts the actual
routed path details from the text log.

Zero exit status does not establish timing closure: this tool can print FAIL
and still exit zero. `manifest.json` preserves all timing observations, final
report Fmax, unsupported constraints and `physical_ready: false`.

Results and disposition are recorded in `RESULTS.md` after the candidate run.
