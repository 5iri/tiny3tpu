#!/usr/bin/env python3
"""Use existing system-clock gaps for instruction decode and register-file reads."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("system_csr", HERE.parent / "system-csr/run.py")
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)


def prepare(out):
    overlay = base.prepare(out)
    path = overlay / "riscv_cpu.v"; cpu = path.read_text()
    groups = [
        ("decoder decoder_inst0 (", {
            "decoder_inst0_rs1_out":5, "decoder_inst0_rs2_out":5, "decoder_inst0_rd_out":5,
            "decoder_inst0_imm_out":32, "decoder_inst0_rs1_valid_out":1,
            "decoder_inst0_rs2_valid_out":1, "decoder_inst0_rd_valid_out":1,
            "decoder_inst0_opcode_out":7, "decoder_inst0_instr_id_out":7}),
        ("registerfile rf_inst0 (", {"rf_inst0_rs1_value_out":32, "rf_inst0_rs2_value_out":32})]
    for marker, ports in groups:
        start = cpu.index(marker); end = cpu.index("    );", start) + len("    );")
        instance = cpu[start:end]
        for name in ports:
            assert instance.count("(" + name + ")") == 1
            instance = instance.replace("(" + name + ")", "(" + name + "_raw)")
        registers = "\n"
        for name, width in ports.items():
            registers += f"    wire [{width-1}:0] {name}_raw;\n    reg [{width-1}:0] {name}_q;\n"
            registers += f"    assign {name} = SYSTEM_MUL ? {name}_q : {name}_raw;\n"
        registers += "    always @(posedge system_clk) begin\n        if(rst) begin\n"
        registers += "\n".join(f"            {name}_q <= 0;" for name in ports)
        registers += "\n        end else begin\n"
        registers += "\n".join(f"            {name}_q <= {name}_raw;" for name in ports)
        registers += "\n        end\n    end\n"
        cpu = cpu[:start] + instance + registers + cpu[end:]
    check = "        always @(posedge clk) if(!rst) begin\n"
    for _, ports in groups:
        for name in ports:
            check += f"            if({name} !== {name}_raw)\n"
            check += f'                $fatal(1,"Stale decode/register-file result {name} pc=%h",if_id_pc_out);\n'
    check += "        end\n"
    marker = "        wire signed [32:0] a_ref"
    assert marker in cpu
    path.write_text(cpu.replace(marker, check + marker, 1))
    return overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify")); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    overlay = prepare(out)
    if args.mode == "verify":
        base.base.base.prove(out)
        base.base.base.base.base.verify(out, overlay, unit=False)
    paths = list(overlay.glob("*.v")) + [Path(__file__)] + list(out.glob("*tb.sv"))
    (out / (args.mode + "-sources.json")).write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, indent=2) + "\n")


if __name__ == "__main__": main()
