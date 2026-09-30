#!/usr/bin/env python3
"""Build an isolated UberDDR3 KC705 trial using open-source tools only.

Does not export a bitstream or program the board. A failed route is rejected.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from kc705_ddr_only_build import constraints
from kc705_open_build import validate_route_log

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "hardware/kc705_uberddr3"
UPSTREAM = ROOT / "third_party/uberddr3"

# A variable part-select makes Yosys build a wide read-mux followed by a
# write-demux. Decode each byte once instead; preserve all 64 byte-mask tests.
BIST_BEFORE = """calib_data <= {wb_sel_bits{8'haa}}; // set the rest (masked) to aa
                                calib_data[8*write_by_byte_counter +: 8] <= calib_data_randomized[8*write_by_byte_counter +: 8];"""
BIST_AFTER = """for (integer bist_byte = 0; bist_byte < wb_sel_bits; bist_byte = bist_byte + 1)
                                    calib_data[8*bist_byte +: 8] <= (write_by_byte_counter == bist_byte)
                                        ? calib_data_randomized[8*bist_byte +: 8] : 8'haa;"""
FINISH_BEFORE = "if( write_test_address_counter == { 2'b11 , {(wb_addr_bits_sim-2){1'b1}} } ) begin"
# calib_we is the PREVIOUS operation: one means this cycle issues a read.
# Otherwise the alternating test finishes after writing its final address.
FINISH_AFTER = "if(calib_we && write_test_address_counter == { 2'b11 , {(wb_addr_bits_sim-2){1'b1}} }) begin"
DRAIN_BEFORE = """FINISH_READ: begin
                        calib_stb <= 0;
                        if(train_delay == 0) begin"""
DRAIN_AFTER = """FINISH_READ: begin
                        if (!o_wb_stall_calib) calib_stb <= 0;
                        if(train_delay == 0 && !calib_stb &&
                           (BIST_MODE == 0 || correct_read_data >=
                            ((BIST_MODE == 2 ? 32'd3 : 32'd1) << wb_addr_bits_sim))) begin"""
ODT_BEFORE = """else if(instruction_address == 17) begin
                            write_calib_dqs <= 1'b1;
                            write_calib_odt <= 1'b1;"""
ODT_AFTER = """else if(instruction_address == 16 && delay_counter <= 3) begin
                            // Enable DRAM ODT before DQS starts write leveling.
                            write_calib_odt <= 1'b1;
                            pause_counter <= 0;
                        end
                        else if(instruction_address == 17) begin
                            write_calib_dqs <= 1'b1;"""
WL_EXIT_BEFORE = """        cmd_d[PRECHARGE_SLOT][cmd_len-1-DUAL_RANK_DIMM:0] = {(!delay_counter_is_zero), instruction[DDR3_CMD_START-1:DDR3_CMD_END] | {3{(!delay_counter_is_zero)}} , cmd_odt, cmd_ck_en, cmd_reset_n, 
                        instruction[MRS_BANK_START:(MRS_BANK_START-BA_BITS+1)], instruction[ROW_BITS-1:0]};"""
WL_EXIT_AFTER = WL_EXIT_BEFORE + """
        // Instruction 17 is MR1_WL_DIS. Hold it off while write leveling is
        // active: START_WRITE_LEVEL pauses the ROM at 17 and begins DQS pulses
        // there, so issuing the ROM command unchanged would disable WL first.
        // Once training succeeds, ISSUE_WRITE_1 releases the pause and this
        // MRS is issued before instruction 18's required tMOD delay.
        if (instruction_address == 5'd17 &&
            (state_calibrate == START_WRITE_LEVEL || state_calibrate == WAIT_FOR_FEEDBACK))
            cmd_d[PRECHARGE_SLOT][cmd_len-1-DUAL_RANK_DIMM -: 4] = {1'b0, 3'b111};"""
TOP_RAW_PORT_BEFORE = "        output wire uart_tx\n"
TOP_RAW_PORT_AFTER = "        output wire uart_tx,\n        output wire o_debug_raw_dq0\n"
TOP_RAW_CONNECT_BEFORE = ".o_ddr3_debug_read_dqs_p(/*o_ddr3_debug_read_dqs_p*/),"
TOP_RAW_CONNECT_AFTER = ".o_debug_raw_dq0(o_debug_raw_dq0),\n                " + TOP_RAW_CONNECT_BEFORE
PHY_RAW_PORT_BEFORE = "        output wire o_controller_idelayctrl_rdy,"
PHY_RAW_PORT_AFTER = PHY_RAW_PORT_BEFORE + "\n        output wire o_debug_raw_dq0,"
PHY_RAW_ASSIGN_BEFORE = "    assign o_controller_idelayctrl_rdy = idelayctrl_rdy && dci_locked;"
PHY_RAW_ASSIGN_AFTER = PHY_RAW_ASSIGN_BEFORE + "\n    assign o_debug_raw_dq0 = idelay_data[0];"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(out, pipeline_bist=False, controller_mhz=100.0, seed=4, mapper="abc",
            placer="heap", io_profile="experimental-sstl15", diagnostic_wl=False,
            diagnostic_uart=False):
    provenance = json.loads((UPSTREAM / "UPSTREAM.json").read_text())
    for name, expected in provenance["sha256"].items():
        if digest(UPSTREAM / name) != expected:
            raise ValueError(f"Pinned upstream source changed: {name}")
    # Keep the upstream snapshot pristine. Expose its existing BIST counters
    # through unused debug bits, so a retry cannot conceal a memory error.
    source = (UPSTREAM / "rtl/ddr3_controller.v").read_text()
    before = "assign o_debug1 = {27'd0, state_calibrate[4:0]};"
    after = "assign o_debug1 = {|wrong_read_data, |correct_read_data, 25'd0, state_calibrate[4:0]};"
    if diagnostic_wl:
        # Preserve the sticky BIST flags while exposing feedback and lane on LEDs.
        after = "assign o_debug1 = {|wrong_read_data, |correct_read_data, 21'd0, stored_write_level_feedback, lane[2:0], odelay_data_cntvaluein[lane]};"
    if diagnostic_uart:
        after = ("assign o_debug1 = {|wrong_read_data, |correct_read_data, "
                 "i_phy_idelayctrl_rdy, write_calib_odt, write_calib_dqs, "
                 "o_phy_dqs_tri_control, o_phy_dq_tri_control, "
                 "i_phy_iserdes_data[lane_times_8], o_phy_toggle_dqs, "
                 "10'd0, "
                 "prev_write_level_feedback, write_level_fail[lane], "
                 "(delay_before_write_level_feedback == 0), reset_done, "
                 "stored_write_level_feedback, lane[2:0], odelay_data_cntvaluein[lane]};")
    if source.count(before) != 1:
        raise ValueError("Upstream debug assignment changed")
    if source.count(BIST_BEFORE) != 1:
        raise ValueError("Upstream masked BIST write changed")
    if source.count(FINISH_BEFORE) != 1:
        raise ValueError("Upstream BIST finish condition changed")
    if source.count(DRAIN_BEFORE) != 1:
        raise ValueError("Upstream BIST drain condition changed")
    if source.count(ODT_BEFORE) != 1:
        raise ValueError("Upstream write-level ODT/DQS sequence changed")
    if source.count(WL_EXIT_BEFORE) != 1:
        raise ValueError("Upstream DDR command output structure changed")
    generated = out / "ddr3_controller.v"
    generated.write_text(source.replace(before, after).replace(BIST_BEFORE, BIST_AFTER)
                         .replace(FINISH_BEFORE, FINISH_AFTER).replace(DRAIN_BEFORE, DRAIN_AFTER)
                         .replace(ODT_BEFORE, ODT_AFTER).replace(WL_EXIT_BEFORE, WL_EXIT_AFTER))
    top_source = (UPSTREAM / "rtl/ddr3_top.v").read_text()
    phy_source = (UPSTREAM / "rtl/ddr3_phy.v").read_text()
    for label, text, anchor, count in (
        ("top raw port", top_source, TOP_RAW_PORT_BEFORE, 1),
        ("top raw connection", top_source, TOP_RAW_CONNECT_BEFORE, 2),
        ("PHY raw port", phy_source, PHY_RAW_PORT_BEFORE, 1),
        ("PHY raw assignment", phy_source, PHY_RAW_ASSIGN_BEFORE, 1),
    ):
        if text.count(anchor) != count:
            raise ValueError(f"Upstream {label} structure changed")
    generated_top = out / "ddr3_top.v"
    generated_phy = out / "ddr3_phy.v"
    generated_top.write_text(top_source.replace(TOP_RAW_PORT_BEFORE, TOP_RAW_PORT_AFTER)
                        .replace(TOP_RAW_CONNECT_BEFORE, TOP_RAW_CONNECT_AFTER, 1))
    generated_phy.write_text(phy_source.replace(PHY_RAW_PORT_BEFORE, PHY_RAW_PORT_AFTER)
                        .replace(PHY_RAW_ASSIGN_BEFORE, PHY_RAW_ASSIGN_AFTER))
    sources = [HW / "kc705_uberddr3_top.sv", HW / "kc705_uberddr3_status.sv",
               HW / "kc705_uberddr3_uart_diag.sv",
               generated_top, generated, generated_phy]
    receiver = HW / "bist_receiver.vh"
    if pipeline_bist:
        start = source.index("    always @(posedge i_controller_clk) begin\n        if(sync_rst_controller) begin\n            check_test_address_counter <= 0;")
        end = source.index("    /********", start)
        old_receiver = source[start:end]
        modified = generated.read_text()
        if modified.count(old_receiver) != 1:
            raise ValueError("Upstream BIST receiver changed")
        generated.write_text(modified.replace(old_receiver, receiver.read_text()))
    manifest = dict(target="kc705_uberddr3", cpu=False, firmware=False, tpu=False,
                    dma=False, ethernet=False, controller_mhz=controller_mhz,
                    ddr_clock_mhz=4*controller_mhz, system_mhz=100,
                    memory_bytes=2**30, byte_lanes=8, bist_mode=1, bist_datamask=True,
                    pipeline_bist=pipeline_bist,
                    placement_seed=seed, mapper=mapper, placer=placer, io_profile=io_profile,
                    simulation=False, hardware_memory_pass=False, upstream=provenance,
                    source_transforms=[dict(before=before, after=after),
                                       dict(before=BIST_BEFORE, after=BIST_AFTER),
                                       dict(before=FINISH_BEFORE, after=FINISH_AFTER),
                                       dict(before=DRAIN_BEFORE, after=DRAIN_AFTER),
                                       dict(before=ODT_BEFORE, after=ODT_AFTER),
                                       dict(before=WL_EXIT_BEFORE, after=WL_EXIT_AFTER),
                                       dict(before=TOP_RAW_PORT_BEFORE, after=TOP_RAW_PORT_AFTER),
                                       dict(before=TOP_RAW_CONNECT_BEFORE, after=TOP_RAW_CONNECT_AFTER),
                                       dict(before=PHY_RAW_PORT_BEFORE, after=PHY_RAW_PORT_AFTER),
                                       dict(before=PHY_RAW_ASSIGN_BEFORE, after=PHY_RAW_ASSIGN_AFTER)],
                    diagnostic_write_level_feedback=diagnostic_wl,
                    diagnostic_uart=diagnostic_uart,
                    sha256={str(p): digest(p) for p in sources + [Path(__file__), UPSTREAM / "UPSTREAM.json"]
                            + ([receiver] if pipeline_bist else [])})
    (out / "hardware-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return sources


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["generate", "synth", "route"])
    p.add_argument("--build-dir", type=Path, default=ROOT / "build-uberddr3")
    # The current openXC7 backend cannot implement SSTL15_T_DCI/DCI_CASCADE.
    # Selecting this trial is explicit; record the lack of FPGA DQ termination.
    p.add_argument("--ddr-io", choices=["experimental-sstl15"], required=True)
    p.add_argument("--yosys", type=Path, default=Path.home() / ".apio/packages/oss-cad-suite/bin/yosys")
    p.add_argument("--nextpnr", type=Path, default=ROOT / "build-vexriscv/nextpnr-preg-grade2/nextpnr-xilinx")
    p.add_argument("--chipdb", type=Path, default=Path("/tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin"))
    p.add_argument("--seed", type=int, default=4)
    p.add_argument("--mapper", choices=["abc9", "abc"], default="abc")
    p.add_argument("--placer", choices=["heap", "sa"], default="heap")
    p.add_argument("--onehot", action="store_true", help="Ask Yosys to recode the calibration FSM")
    p.add_argument("--pipeline-bist", action="store_true", help="Register partial BIST comparisons")
    p.add_argument("--diagnostic-wl", action="store_true",
                   help="Show write-level feedback and active lane on LEDs 6:3")
    p.add_argument("--diagnostic-uart", action="store_true",
                   help="Stream write-level PHY and feedback diagnostics via KC705 USB UART")
    p.add_argument("--controller-mhz", choices=["100", "83.333"], default="100",
                   help="Controller speed; 83.333 keeps the other system clock at 100 MHz")
    a = p.parse_args()
    out = a.build_dir.resolve()
    if any(c.isspace() or c in '\";\\' for path in (out, ROOT) for c in str(path)):
        p.error("Yosys paths must not contain spaces, quotes, or separators")
    if a.stage == "route" and (not a.chipdb.is_file() or not a.nextpnr.is_file()):
        p.error("Routing requires an existing --chipdb and --nextpnr")
    out.mkdir(parents=True, exist_ok=True)
    controller_period = 10000 if a.controller_mhz == "100" else 12000
    controller_mhz = 100.0 if controller_period == 10000 else 1000 / 12
    ddr_mhz = 4 * controller_mhz
    sources = prepare(out, a.pipeline_bist, controller_mhz, a.seed,
                      a.mapper, a.placer, a.ddr_io, a.diagnostic_wl, a.diagnostic_uart)
    constraints(out, a.ddr_io)
    with (out / "kc705.xdc").open("a") as xdc:
        xdc.write("set_property PACKAGE_PIN K24 [get_ports {uart_tx}]\n"
                  "set_property IOSTANDARD LVCMOS25 [get_ports {uart_tx}]\n")
    if a.stage == "generate":
        return

    def run(command, name):
        print(f"Running {name}: {out / (name + '.log')}", flush=True)
        with (out / (name + ".log")).open("w") as log:
            result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise SystemExit((out / (name + ".log")).read_text()[-6000:])

    script = ["read_verilog -sv " + " ".join(map(str, sources)),
              "read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v",
              f"chparam -set CONTROLLER_CLK_PERIOD {controller_period} -set DDR3_CLK_PERIOD {controller_period // 4} "
              f"-set DIAGNOSTIC_WL {int(a.diagnostic_wl)} "
              f"-set DIAGNOSTIC_UART {int(a.diagnostic_uart)} kc705_uberddr3_top",
              "hierarchy -check -top kc705_uberddr3_top",
              # Keep reset/enable logic intact until synth_xilinx's own FSM
              # extraction; an early full opt can turn state FFs into SDFFEs.
              "proc; opt_clean; check -assert",
              f"synth_xilinx -family xc7 -flatten -nowidelut {'-abc9' if a.mapper == 'abc9' else ''} "
              f"-top kc705_uberddr3_top -json {out / 'soc.json'}",
              "check -assert", "stat"]
    if a.onehot:
        script.insert(3, 'setattr -set fsm_encoding "one-hot" w:state_calibrate')
    (out / "synth.ys").write_text("\n".join(script) + "\n")
    run([a.yosys, "-Q", "-T", "-s", out / "synth.ys"], "synth")
    if a.stage == "synth":
        return
    clocks = [("clk200", 200), ("controller_clk", controller_mhz),
              ("ddr_clk", ddr_mhz), ("ref_clk", 200), ("system_clk", 100)]
    (out / "clocks.py").write_text(f"for name, mhz in {clocks!r}:\n    ctx.addClock(name, mhz)\n")
    run([a.nextpnr, "--chipdb", a.chipdb, "--xdc", out / "kc705.xdc", "--freq", str(controller_mhz),
         "--seed", a.seed, "--placer", a.placer, "--pre-pack", out / "clocks.py", "--json", out / "soc.json",
         "--write", out / "soc_routed.json", "--fasm", out / "soc.fasm",
         "--report", out / "timing-report.json"], "route")
    try:
        validate_route_log((out / "route.log").read_text())
    except ValueError as error:
        raise SystemExit(f"Route rejected: {error}. The output is not a board candidate.")
    print(f"{controller_mhz:g} MHz DDR controller route guard passed. Physical DDR3 testing is still required.")


if __name__ == "__main__":
    main()
