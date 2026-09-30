#!/usr/bin/env python3
"""Prove the BIST rewrite and test failure reporting; not a DDR PHY simulation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from kc705_uberddr3_build import BIST_BEFORE, BIST_AFTER, prepare


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-dir", type=Path, default=ROOT / "build-uberddr3-tests")
    p.add_argument("--yosys", type=Path, default=Path.home() / ".apio/packages/oss-cad-suite/bin/yosys")
    p.add_argument("--pipeline-bist", action="store_true")
    a = p.parse_args()
    out = a.build_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prepare(out, a.pipeline_bist)  # Also checks every pinned upstream hash and patch anchor.

    # Use the exact old/new expressions from the build transformation, with
    # arbitrary 512-bit input data and every possible byte selection.
    def expression(block, name):
        return block.replace("calib_data[", name + "[").replace("calib_data <=", name + " <=")
    proof = """module bist_equivalence(input [511:0] calib_data_randomized,
        input [5:0] write_by_byte_counter, output equal);
        localparam wb_sel_bits = 64;
        reg [511:0] original, rewritten;
        always @* begin
    """ + expression(BIST_BEFORE, "original") + "\nend\nalways @* begin\n" + expression(BIST_AFTER, "rewritten") + """
        end
        assign equal = original == rewritten;
    endmodule
    """
    (out / "bist_equivalence.sv").write_text(proof)
    commands = f"read_verilog -sv {out / 'bist_equivalence.sv'}; prep -top bist_equivalence; sat -verify -prove equal 1 -show-inputs"
    with (out / "equivalence.log").open("w") as log:
        subprocess.run([str(a.yosys), "-Q", "-p", commands], stdout=log, stderr=subprocess.STDOUT, check=True)
    receiver = (ROOT / "hardware/kc705_uberddr3/bist_receiver.vh").read_text()
    start = receiver.index("    localparam KC705_BIST_CHUNKS")
    chunks = receiver[start:receiver.index(";", start)+1]
    start = receiver.index("                for (integer chunk")
    compare = receiver[start:receiver.index("            end", start)]
    comparison_proof = """module comparison_equivalence(input [511:0] o_wb_data, correct_data, output equal);
        localparam wb_data_bits = 512;
    """ + chunks + """
        reg [KC705_BIST_CHUNKS-1:0] kc705_bist_match;
        always @* begin
    """ + compare + """
        end
        assign equal = (&kc705_bist_match) == (o_wb_data == correct_data);
    endmodule
    """
    (out / "comparison_equivalence.sv").write_text(comparison_proof)
    commands = f"read_verilog -sv {out / 'comparison_equivalence.sv'}; prep -top comparison_equivalence; sat -verify -prove equal 1"
    with (out / "comparison-equivalence.log").open("w") as log:
        subprocess.run([str(a.yosys), "-Q", "-p", commands], stdout=log, stderr=subprocess.STDOUT, check=True)
    subprocess.run(["iverilog", "-g2012", "-s", "kc705_uberddr3_status_tb", "-o", str(out / "status.vvp"),
                    str(ROOT / "hardware/kc705_uberddr3/kc705_uberddr3_status.sv"),
                    str(ROOT / "tests/kc705_uberddr3_status_tb.sv")], check=True)
    result = subprocess.run(["vvp", "-n", str(out / "status.vvp")], check=True, text=True, capture_output=True)
    (out / "status.log").write_text(result.stdout + result.stderr)
    if "PASS:" not in result.stdout:
        raise RuntimeError("Simulation ended without passing")
    subprocess.run(["iverilog", "-g2012", "-s", "kc705_uberddr3_bist_tb", "-o", str(out / "bist.vvp"),
                    str(out / "ddr3_controller.v"),
                    str(ROOT / "hardware/kc705_uberddr3/kc705_uberddr3_status.sv"),
                    str(ROOT / "tests/kc705_uberddr3_bist_tb.sv")], check=True)
    scenarios = [(mode, 1, 0) for mode in range(12)]
    scenarios += [(0, 24, offset) for offset in range(7)] + [(3, 24, 0)]
    for mode, delay, offset in scenarios:
        bist = subprocess.run(["vvp", "-n", str(out / "bist.vvp"),
                               f"+mode={mode}", f"+delay={delay}", f"+offset={offset}"],
                              text=True, capture_output=True, timeout=30)
        (out / f"bist-{mode}-{delay}-{offset}.log").write_text(bist.stdout + bist.stderr)
        if bist.returncode or "PASS:" not in bist.stdout:
            raise RuntimeError(bist.stdout + bist.stderr)
        print(next(line for line in bist.stdout.splitlines() if line.startswith("PASS:")))
    (out / "test-result.json").write_text(json.dumps(dict(
        byte_decode_equivalence=True, comparison_equivalence=True, failure_reporting=True, abstract_bist_memory=True,
        pipeline_bist=a.pipeline_bist,
        bist_scenarios=len(scenarios),
        controller_phy_simulation=False, hardware_memory_pass=False), indent=2) + "\n")
    print("PASS: byte rewrite proven equivalent for all 512-bit data and all 64 byte positions")
    print("PASS: partial comparisons proven equivalent for all pairs of 512-bit data")
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
