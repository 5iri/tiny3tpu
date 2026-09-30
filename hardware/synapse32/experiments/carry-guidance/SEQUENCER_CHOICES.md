# Same-cycle sequencer choices

The stock-column minimum worst probe is now **11.038 ns**, from
`build-ddr-guarded-branch-zqcs-choice-v2-grade2-route/seed-5`. Its three expanded
probes are 10.936/10.936/11.038 ns; native reports are 90.60 MHz system and
97.99 MHz CPU. The integrity audit passes and the timing gate rejects.
This is a small diagnostic improvement over 11.093 ns, not 100 MHz closure.

The parent is the guarded-branch/unused-DSP-input mapping, followed by a
same-edge ZQCS zero flag. The flag's control-cone SAT and actual 27-bit counter
induction preserve the maintenance event cycle. Its measured target improves
from 11.093 to 8.798 ns at matching seed 5, but the whole route reaches
11.603 ns because another path becomes critical.

The sequencer change precomputes both values of the late compare input to one
measured write-data endpoint, then selects with a final LUT3. Yosys maps the
two alternatives into six LUTs. Actual Xilinx primitive SAT covers all 16
independent cut inputs. Only that endpoint's combinational cone is changed;
the original output, other consumers, all state and instruction latency are
preserved. Its target improves from 11.603 to 9.317 ns. The new longest probe
runs from a DDR write-address register through offset arithmetic and address
change detection into a native-port converter selector.

The initial cofactor harness stopped at Yosys `$scopeinfo` metadata. Version 2
accepts only connection-free scope records and `$lut` cells, then proves the
actual translated LUT netlist. The failed initial directory is retained.

| Candidate | Seed 4 worst probe (ns) | Seed 5 worst probe (ns) |
|---|---:|---:|
| Guarded branch + unused upper DSP A inputs | 12.427 | 11.093 |
| Plus same-edge ZQCS zero flag | 11.967 | 11.603 |
| Plus late sequencer choice | 11.774 | **11.038** |

Other seed-5 trials are rejected: sign factoring on the retained parent
11.752 ns; sign factoring plus timer flag 12.312 ns; a six-input sequencer
LUT/MUX collapse 12.601 ns; captured multiply signedness 11.825 ns.
All completed integrity audits pass. These are mapped-netlist transformations
composed with the parent's actual synthesis/workload evidence, not new
full-workload simulations. The parent full diagnostic remains 1,659,843
instructions / 2,084,686 enabled CPU edges = 0.796208 IPC, over 11,544,608 system
cycles. No firmware or clock constraint changes are made.

Failing endpoint/domain-pair counts at seed 5 are 287 for the retained parent,
255 for the zero-flag candidate and 319 for the choice candidate. These are
not counts of every combinational path. The lower worst delay therefore does
not establish a uniform improvement across endpoints.

Registered primitive values assume the stock KC705 -2 / 1.0 V configuration.
Carry/cascade costs remain symbolic. Generic delays, clock skew/hold, reset
recovery/removal and DDR IO remain unvalidated. No default promotion or
physical signoff is claimed.

Follow-up stock-column trials retain the same clocks and firmware:

- Factoring the DDR comparison around offset carry bit 13 passes actual
  primitive SAT over 50 cut inputs. It adds 55 combinational LUTs and no state.
  The converter-selector endpoint improves from 11.038 to 9.669 ns, but global
  probes regress to 11.453/11.453/11.853 ns. It is not selected.
- Placement timing weight 20 gives 11.587/11.587/12.338 ns at seed 5.
- Placement timing weight 10 gives 11.541/11.541/11.641 ns at seed 5.

All three integrity audits pass and all timing gates reject. The best remains
11.038 ns at weight 40. Separate fixed-layout controls and bounded local moves
are documented in [PIN_MAPS.md](PIN_MAPS.md).
