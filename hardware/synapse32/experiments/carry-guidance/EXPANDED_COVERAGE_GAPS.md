# Coverage remaining after the 100 MHz diagnostic milestone

Candidate: `build-grade2-incremental-readvalid-arrival-swap`. Native system 100.03 MHz; expanded probes 9.997 ns. Physical acceptance remains false.

The native report lists 11,703 ignored dynamic ports. Reconciliation with expanded model decisions finds:

| Category | Ports | Evidence |
|---|---:|---|
| Unobserved RAMD32 halves | 7,098 | 973 physical cells have no output consumers in routed connectivity |
| Disabled BRAM B ports | 896 | 16 RAMB36E1 profiles have zero B read/write widths and bypassed output registers; listed address/data ports have no drivers in either graph or final JSON |
| Still unresolved | 3,709 | No expanded timing classification or valid exclusion identified |

These exclusions already existed in the model. This audit introduces no false paths and does not change timing values or the original acceptance gate. Negative controls add a live LUTRAM consumer and enable a BRAM B write port; both invalidate the exclusions.

The first stronger validator incorrectly required constant primitive drivers for the inactive BRAM pins; it failed. A second attempt requiring a graph constant driver also failed. The successful v3 audit explicitly records absence of graph and final JSON drivers and verifies that the affected B ports are disabled. No constant-driver claim is retained.

Unresolved ports by primitive family include OSERDESE2 (1,396), ISERDESE2 (832), ODELAYE2 (525), IDELAYE2 (320), IO/pad/inverter resources, three IDELAYCTRLs, one CPU BUFGCTRL enable and PLL ports. These need profile-specific timing coverage and valid constraints; simply labeling them would not prove timing.

Independent remaining physical requirements: qualified generic FF/LUT/mux and carry delays, clock skew and hold, reset recovery/removal, DDR PHY IO constraints/calibration, plus validation of the final image and workload. The 3 ps diagnostic margin is not a validated hardware margin.

Evidence:
- `tools/synapse32_reconcile_expanded_port_coverage.py`
- `build-grade2-incremental-readvalid-arrival-swap/expanded-port-reconciliation.json`
- `tools/synapse32_validate_memory_exclusions_v3.py`
- `build-grade2-incremental-readvalid-arrival-swap/memory-exclusion-evidence-v3.json`

All audit jobs completed. The full goal remains active.

## CPU clock-enable setup probe and simulation correction

`build-grade2-bufgce-setup-probe/manifest.json` adds the actual BUFGCE CE0 setup endpoint to a copy of the retained carry-0.1 graph. It validates the packed BUFGCTRL profile and constant control pins. UG472 (v1.14, pages 42 and 45) specifies CE timing against the rising edge; DS182 Table 36 gives 0.14 ns setup and 0.38 ns hold for the selected -2, 1.0 V grade. The computed setup arrival including setup is **6.750 ns**, within 10 ns. The hold requirement is recorded but minimum data delay and clock skew have not been verified. This supplementary probe does not change the production acceptance gate or claim complete coverage.

The simulation clock gate previously sampled CE only at the falling edge, missing changes later in the low phase. `synapse32_clock_enable.sv` now latches CE throughout low and preserves complete high pulses. The hardware BUFGCE branch is byte-identical to the prior version. `tb_clock_enable_low_phase.sv` checks late enable/disable and high-phase pulse preservation; the corrected model passes and the original model fails the late-enable case. Evidence and source hashes are in `build-clock-enable-low-phase-test/manifest.json`. This changes simulation fidelity, not routed hardware or hardware pipeline latency.

## Minimum-delay backend readiness

`tools/synapse32_audit_minimum_delay_support.py` checks the source and linked object selection used by the retained backend. Its report is `build-grade2-minimum-delay-audit/report.json`. The Xilinx `DelayInfo` implementation returns the same scalar for minimum and maximum delay. Cell lookups and routed pip calculations use maximum database delays. The exporter emits maximum cell/CQ delays; changing the path traversal to minimize those values would therefore **not** constitute hold analysis. Global clock hop constants are calibrated against a VC707 reference, not qualified KC705 insertion/skew bounds. No physical hold failure is inferred from this audit; hold remains unverified.

The next backend work must preserve independently qualified minimum/maximum bounds and export launch/capture clock paths. Until then, the recorded CE hold requirement of 0.38 ns cannot be compared to a trustworthy earliest data arrival. No RTL or firmware was changed by this audit.

## Retained chip database bounds inventory

`build-grade2-chipdb-delay-bounds/report.json` inventories the exact `kc705.bin` hash used by the retained routed candidate. The binary identifies `xc7k325tffg900-2`, has one speed-grade record, 127 wire classes and 260 pip timing classes. Of those pip classes, 225 store distinct minimum/maximum values; 32 have zero minimum. There are **zero timed tile types and zero primitive cell delay entries**. Routing bound fields exist, but their physical provenance remains unqualified; primitive delay qualification cannot be solved merely by exposing the existing database fields.

The read-only inspector is `tools/synapse32_inspect_chipdb_delay_bounds.py`. Its initial byte-offset interpretation was rejected by the version assertion before producing output. The corrected interpretation uses the backend's four-byte-scaled relative pointers (`arch.h` RelPtr), passes structural checks and matches the retained candidate database hash. This inventory does not change any routing or timing acceptance.

## Flip-flop CQ sensitivity changes the optimization target

`build-grade2-ff-cq-sensitivity/manifest.json` records fresh analysis with the same retained routing, all existing setup values, and the supplementary BUFGCE endpoint. Replacing the generic 0.1 ns FF CQ with the DS182 Table 31 -2/1.0 V TCKO value of 0.27 ns raises system setup maximum from 9.997 to **10.167 ns**, and CPU maximum from 9.947 to **10.117 ns**. A uniform 0.32 ns TSHCKO probe gives **10.217 ns** system and **10.167 ns** CPU. These are sensitivity probes, not a fully mapped primitive model: AQ versus mux output mapping, path-specific setup, other primitive delays, route bounds and clock skew remain unresolved. They demonstrate that the 3 ps legacy diagnostic margin is not robust to documented FF CQ values. Future optimization must address these newly exposed margins while retaining throughput.

## Current candidate bitstream

The retained `build-grade2-incremental-cq-tpu-output-pairs` route now has an open-source KC705 bitstream at `build-grade2-incremental-cq-tpu-output-pairs-bit/latest.bit`. The source route passed exact composition equivalence for the three proved rewrites and the expanded setup probes at 9.986 ns. `build-grade2-incremental-cq-tpu-output-pairs-bit/manifest.json` hashes the route, tools, frame database, FASM, frames, bitstream and readback. OpenXC7 readback reproduces every non-ECC configuration word; 442 additional readback frames contain zero data outside the ECC word. `openFPGALoader --scan-usb` found no attached device, so no board programming or UART test occurred. This bitstream is an experimental image: the mapped FF/control setup probe is 10.185 ns, and hold/skew, DDR PHY IO and complete primitive timing remain unvalidated.

## Combinational DSP timing mode sensitivity

The retained route has 32 combinational DSP48E1 multipliers with `USE_DPORT=FALSE`, `USE_MULT=MULTIPLY`, direct A input and A/M/P/AD registers bypassed. The backend assigns a pooled **5.40 ns** delay to every A-to-timed-output arc. The available Artix-7 `DSP_R.sdf` contains a matching mode's A-to-P maximum of **3.841 ns**. `tools/synapse32_dsp_mode_delay_sensitivity.py` checks the parameters and changes only those A-to-P graph arcs (46,080 bit-pair arcs); the original setup graph maximum becomes 9.948 ns. Applying the same exploratory change to the mapped FF/control setup graph gives **10.136 ns** with 36 endpoint/domain pairs over 10 ns, led by a DDR/control SR path. Evidence is in `build-grade2-incremental-cq-tpu-output-pairs-dsp-mode-sensitivity/` and `build-grade2-incremental-cq-tpu-output-pairs-mapped-dsp-mode/`.

This is **not** an accepted Kintex-7 -2 model. The mode-specific SDF is from Artix-7 and its timing corner has not been qualified for KC705. The experiment establishes that the generic 5.40 ns multiplier arc drives the current reported bottleneck and reveals the next path if a proper Kintex mode bound proves shorter. No route, RTL, bitstream or timing acceptance was changed.
