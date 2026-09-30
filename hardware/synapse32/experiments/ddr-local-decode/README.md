# DDR decode composition and local reset routing

**Native target reached: 100.29 MHz system / 106.38 MHz CPU**, seed 4,
with system/CPU crossings at 9.16/9.61 ns. These are actual nextpnr routed
results at unchanged 100 MHz constraints. Native timing remains incomplete;
this does not establish physical KC705 timing closure. The system's native
margin is approximately 29 ps.

Starting from the verified local DDR layout, four identical copies of the
final reset FDPE drive 125 combinational reset loads in nearby groups. Their
INIT, clock, D, CE and asynchronous preset inputs match the original stage.
Collapsing these copies restores the exact original state equations. There
is no additional reset cycle. Placement runs the original legality checks.

The reported DDR command-control path then crossed three LUT levels. Its
combined function has five independent inputs. The final LUT3 becomes a LUT5
that directly evaluates those inputs; the two upstream LUTs remain for their
other consumers. An exhaustive 32-assignment check compares the original
cone with the new truth table, and mapped Xilinx LUT primitive simulation
independently verifies the same 32 assignments. All other packed logic is
compared exactly through its logical/physical pin mappings.

The original placement produced 97.53 MHz system / 101.68 MHz CPU. Reset
copies with locked incremental routing give 97.25/104.44 MHz; composing the
decode gives 97.85/104.44 MHz (seed 2). The next reported path is calibration
timer control. A further candidate moves its standalone LUT from
`SLICE_X114Y43/C6LUT` to `SLICE_X119Y32/A6LUT` to shorten the adjoining routes.
A second timer-control LUT moves from `SLICE_X121Y42/B6LUT` to
`SLICE_X123Y35/C6LUT`. These changes reach 99.46/101.68 MHz after rerouting the
critical TPU operand connection. Finally, two TPU operand LUT/FF pairs move
from `SLICE_X93Y122/A6LUT,AFF` and `SLICE_X94Y117/B6LUT,BFF` to
`SLICE_X99Y141/A6LUT,AFF` and `SLICE_X97Y142/A6LUT,AFF`. This reaches the native
100.29/106.38 MHz target. The pairs keep their original relative constraints,
INIT values, clocks, resets, enables and data functions. No pipeline stage is
added. A whole-byte routing trial regressed to 97.63 MHz and is not selected.

Incremental routing uses the [lossless checkpoint serializer](../routing-import/README.md).
Only nets with identical physical endpoints are retained. The original clock
constraints remain in force. The integrity audit checks retained resource IDs,
net delays, variable-input timing coverage, output classifications and all
clock arcs. Constant-only pin annotations may differ after legalization;
these are checked against actual PSEUDO_GND/VCC drivers before exclusion from
variable-input comparisons. The explicitly changed decode is separately
proved. No timing arcs are removed from the nextpnr run itself.

Fresh smoke and 45-shape simulations of the source configuration exactly
match the current UART candidate's PROFILE, METRICS and DMA records. These
post-mapping transformations preserve combinational functions and reset
state equations; the 45-shape test is not a gate-level LiteDRAM/PHY simulation.
Full workload remains 11,544,608 system cycles and 0.796208 CPU IPC. GEMM
windows remain 5,479,755 system cycles and 0.801148 pooled IPC.

Reproduction (use fresh output directories):

```sh
python3 tools/synapse32_local_reset_decode_macros.py --groups 4 \
  --extra-moves build-ddr-decode-local-moves/move-timers-pe.json \
  --out build-ddr-local-reset-decode5-pe
python3 tools/synapse32_ddr_decode_primitive_check.py \
  --candidate build-ddr-local-reset-decode5/input.json \
  --out build-ddr-decode5-primitive-proof
python3 tools/synapse32_reroute_reset_decode_tpu.py \
  --parent build-ddr-seeds-parallel-chooser-rest/seed-8/manifest.json \
  --checkpoint build-ddr-local-reset-decode5-pe/placed.json \
  --seed 4 --lock-preserved --out build-ddr-route-reset-decode5-pe-seed4
python3 tools/synapse32_incremental_decode_audit_v4.py \
  --route build-ddr-route-reset-decode5-pe-seed4
python3 tools/synapse32_native_goal_audit.py \
  --route build-ddr-route-reset-decode5-pe-seed4
```

The best expanded-model candidate remains UART reset-control guided seed 8
(11.936/11.936/12.105 ns under the three symbolic probes). Ranking native
reports separately must not promote a layout as physically closed. Firmware,
hardware defaults and the sibling Synapse32 repository are unchanged.

The native winner's expanded probes are **17.773/17.773/18.663 ns** for
symbolic PCOUT/carry values 0/0, 1/0 and 0/0.1 ns. They exceed 10 ns and are
worse than the selected UART diagnostic. The native milestone must not be
used as evidence that the complete physical design can run at 100 MHz.
`tools/synapse32_native_iteration_summary.py` verifies 17 completed route
records, the native goal audit, and both expanded-model artifact sets.
