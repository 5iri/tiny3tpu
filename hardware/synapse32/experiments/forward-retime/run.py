#!/usr/bin/env python3
"""Isolated forwarding-control retiming trial; never programs the FPGA.

The overlay is generated from the divider baseline and existing control
prototype. All evidence stays in --out. Production RTL is not modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = HERE.parent / "divider"
PLAN = HERE.parent / "pipeline-plan"
os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")


def run(command, log):
    print("Running", log.name, flush=True)
    with log.open("w") as output:
        result = subprocess.run(list(map(str, command)), cwd=ROOT,
                                stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text(errors="replace")[-6000:], flush=True)
        raise SystemExit(result.returncode)
    return result.returncode


def prepare(out):
    overlay = out / "overlay"
    overlay.mkdir(parents=True, exist_ok=True)
    original = (BASE / "riscv_cpu.v").read_text()
    start = original.index("    // Instantiate forwarding unit\n")
    end = original.index("    // CSR file signals\n", start)
    reference = original[start:end].replace(
        ".forward_a(forward_a)", ".forward_a(reference_a)").replace(
        ".forward_b(forward_b)", ".forward_b(reference_b)")
    replacement = """    // Compute the selectors for the post-edge pipeline state at ID/EX.
    // MEM/WB advance during holds, so these registers must update on holds.
    synapse32_forward_lookahead forwarding_control (
        .clk(clk), .rst(rst), .flush(pipeline_flush),
        .hold(pipeline_hold), .stall(hazard_stall),
        .ex_mem_flush(div_wait || mem_stage_page_fault_taken ||
                      instr_stage_page_fault_taken ||
                      synchronous_exception_taken || interrupt_taken_qualified),
        .mem_page_fault(mem_stage_page_fault_taken),
        .id_rs1(decoder_inst0_rs1_out), .id_rs2(decoder_inst0_rs2_out),
        .id_rs1_valid(decoder_inst0_rs1_valid_out),
        .id_rs2_valid(decoder_inst0_rs2_valid_out),
        .ex_rs1(id_ex_inst0_rs1_addr_out), .ex_rs2(id_ex_inst0_rs2_addr_out),
        .ex_rd(id_ex_inst0_rd_addr_out),
        .ex_rs1_valid(id_ex_inst0_rs1_valid_out),
        .ex_rs2_valid(id_ex_inst0_rs2_valid_out),
        .ex_rd_valid(id_ex_inst0_rd_valid_out), .ex_instr(id_ex_inst0_instr_id_out),
        .mem_rd(ex_mem_inst0_rd_addr_out), .mem_rd_valid(ex_mem_inst0_rd_valid_out),
        .forward_a_q(forward_a), .forward_b_q(forward_b)
    );
`ifdef SYNAPSE32_FORWARD_ASSERT
    wire [1:0] reference_a, reference_b;
""" + reference + """    // At the falling edge the post-edge pipeline and selectors have settled.
    always @(negedge clk) if (!rst) begin
        if (forward_a !== reference_a || forward_b !== reference_b)
            $fatal(1, "Forwarding invariant failed: A=%b/%b B=%b/%b",
                   forward_a, reference_a, forward_b, reference_b);
    end
`endif

"""
    helper = (PLAN / "forward_lookahead.sv").read_text().replace(
        "// Control-only prototype, NOT a complete CPU overlay.",
        "// Integrated experimental forwarding-control helper.").replace(
        "module forward_lookahead (", "module synapse32_forward_lookahead (")
    (overlay / "riscv_cpu.v").write_text(original[:start] + replacement +
                                        original[end:] + "\n" + helper)
    for name in ("execution_unit.v", "alu.v", "divider.v"):
        (overlay / name).write_bytes((BASE / name).read_bytes())
    return overlay


def verify(args, overlay):
    out = args.out
    source = args.synapse32_dir
    include = "-I" + str(source / "rtl/include")
    run(["iverilog", "-g2012", "-s", "forward_lookahead_tb", include,
         "-o", out / "control.vvp",
         *[source / "rtl/pipeline_stages" / (n + ".v")
           for n in ("ID_EX", "EX_MEM", "MEM_WB", "forwarding_unit")],
         PLAN / "forward_lookahead.sv", PLAN / "forward_lookahead_tb.sv"],
        out / "control-compile.log")
    run(["vvp", out / "control.vvp"], out / "control.log")
    files = [overlay / n for n in ("riscv_cpu.v", "execution_unit.v", "alu.v", "divider.v")]
    files += [source / "rtl" / n for n in ("memory_unit.v", "writeback.v")]
    files += [p for d in ("core_modules", "pipeline_stages")
              for p in sorted((source / "rtl" / d).glob("*.v"))
              if p.name not in ("alu.v", "divider.v")]
    for gated in (0, 1):
        for bench in ("cpu_tb", "cpu_collision_tb"):
            tag = f"{bench}-gated{gated}"
            obj = out / ("obj-" + tag)
            run(["verilator", "--binary", "--timing", "-j", "2", "-Wno-fatal",
                 "--top-module", bench, f"-GGATED={gated}", "--Mdir", obj,
                 "-DSYNAPSE32_CLOCK_SIM", "-DSYNAPSE32_FORWARD_ASSERT", include,
                 *files, ROOT / "hardware/synapse32/synapse32_memory_sequencer.sv",
                 ROOT / "hardware/synapse32/synapse32_clock_enable.sv",
                 BASE / (bench + ".sv")], out / (tag + "-compile.log"))
            run([obj / ("V" + bench)], out / (tag + ".log"))
            print((out / (tag + ".log")).read_text(), flush=True)
    run(["cmake", "-DSOURCE_DIR=" + str(ROOT),
         "-DBINARY_DIR=" + str(out / "dram"),
         "-DSYNAPSE32_DIR=" + str(source), "-DCPU_OVERLAY_DIR=" + str(overlay),
         "-DVERILATOR=verilator", "-DRISCV_GCC=riscv64-unknown-elf-gcc",
         "-DRISCV_OBJCOPY=riscv64-unknown-elf-objcopy", "-DDRAM_TEST=ON",
         "-P", ROOT / "tests/run_synapse32_cpu_test.cmake"], out / "dram.log")
    print((out / "dram.log").read_text(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify", "synth", "route"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--synapse32-dir", type=Path, default=ROOT.parent / "synapse32")
    parser.add_argument("--nextpnr", type=Path,
                        default=Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx"))
    parser.add_argument("--chipdb", type=Path,
                        default=Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin"))
    parser.add_argument("--seed", type=int, default=4)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.synapse32_dir = args.synapse32_dir.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    overlay = prepare(args.out)
    inputs = [Path(__file__), PLAN / "forward_lookahead.sv", PLAN / "forward_lookahead_tb.sv"]
    inputs += sorted(BASE.glob("*.v")) + sorted(BASE.glob("*.sv"))
    inputs += sorted((args.synapse32_dir / "rtl").rglob("*.v"))
    inputs += sorted((args.synapse32_dir / "rtl/include").glob("*.vh"))
    inputs += sorted(overlay.glob("*.v"))
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    (args.out / (args.mode + "-sources.json")).write_text(json.dumps(hashes, indent=2) + "\n")
    if args.mode == "verify":
        verify(args, overlay)
    elif args.mode == "synth":
        run([ROOT / ".venv-ddr-compat/bin/python", ROOT / "tools/kc705_open_build.py",
             "synth", "--synapse32-dir", args.synapse32_dir,
             "--cpu-overlay-dir", overlay, "--build-dir", args.out / "board"],
            args.out / "synth-console.log")
    elif args.mode == "route":
        board = args.out / "board"
        command = [args.nextpnr, "--chipdb", args.chipdb, "--xdc", board / "kc705.xdc",
                   "--freq", "100", "--seed", str(args.seed), "--json", board / "soc.json",
                   "--write", board / "routed.json", "--report", board / "report.json",
                   "--log", board / "route.log"]
        manifest = {"command": list(map(str, command)), "seed": args.seed}
        for name, path in (("nextpnr", args.nextpnr), ("chipdb", args.chipdb),
                           ("xdc", board / "kc705.xdc"), ("netlist", board / "soc.json"),
                           ("firmware", board / "firmware.hex")):
            manifest[name + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (board / "route-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        manifest["exit_code"] = run(command, board / "route-console.log")
        sys.path.insert(0, str(ROOT))
        from tools.synapse32_timing_report import summarize
        manifest["timing"] = summarize((board / "route.log").read_text(),
                                       exit_code=manifest["exit_code"])
        (board / "route-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps(manifest["timing"]["final_clocks"], indent=2), flush=True)
        if not manifest["timing"]["accepted"]:
            print("REJECTED:", manifest["timing"]["reasons"], flush=True)
            raise SystemExit(1)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())


if __name__ == "__main__":
    main()
