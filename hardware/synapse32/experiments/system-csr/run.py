#!/usr/bin/env python3
"""Register CSR read/execute paths inside the existing system-clock gap."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("system_control", HERE.parent / "system-control/run.py")
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)


def prepare(out):
    overlay = base.prepare(out)
    path = overlay / "execution_unit.v"
    ex = path.read_text()
    header, body = ex.split("// Internal signals", 1)
    for name in ("csr_read_data", "csr_valid"):
        body = re.sub(r"(?<!\.)\b" + name + r"\b", name + "_effective", body)
    for name in ("csr_write_data", "csr_write_enable"):
        body = re.sub(r"(?<!\.)\b" + name + r"\b", name + "_raw", body)
    registers = '''
// Address and read enable select architectural CSR state just after CPU +0.
// Capture the read at +1, CSR execution at +2, final EX result at +3.
reg [31:0] csr_read_data_q, csr_write_data_q;
reg csr_valid_q, csr_write_enable_q;
wire [31:0] csr_write_data_raw;
wire csr_write_enable_raw;
always @(posedge system_clk) begin
    if(system_rst) begin
        csr_read_data_q<=0; csr_valid_q<=0;
        csr_write_data_q<=0; csr_write_enable_q<=0;
    end else begin
        csr_read_data_q<=csr_read_data; csr_valid_q<=csr_valid;
        csr_write_data_q<=csr_write_data_raw; csr_write_enable_q<=csr_write_enable_raw;
    end
end
wire [31:0] csr_read_data_effective = SYSTEM_MUL ? csr_read_data_q : csr_read_data;
wire csr_valid_effective = SYSTEM_MUL ? csr_valid_q : csr_valid;
assign csr_write_data = SYSTEM_MUL ? csr_write_data_q : csr_write_data_raw;
assign csr_write_enable = SYSTEM_MUL ? csr_write_enable_q : csr_write_enable_raw;
'''
    path.write_text(header + registers + "\n// Internal signals" + body)
    path = overlay / "riscv_cpu.v"; cpu = path.read_text()
    marker = "        wire signed [32:0] a_ref"
    check = '''        always @(posedge clk) if(!rst) begin
            if(ex_unit_inst0.csr_read_data_effective !== csr_read_data ||
               ex_unit_inst0.csr_valid_effective !== csr_valid ||
               csr_write_data !== ex_unit_inst0.csr_write_data_raw ||
               csr_write_enable !== ex_unit_inst0.csr_write_enable_raw)
                $fatal(1,"Stale system CSR value pc=%h",id_ex_inst0_pc_out);
        end
'''
    assert marker in cpu
    path.write_text(cpu.replace(marker, check + marker, 1))
    return overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "execution", "verify"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    overlay = prepare(out)
    if args.mode in ("execution", "verify"):
        base.verify_execution(out, overlay)
    if args.mode == "verify":
        base.base.prove(out)
        base.base.base.base.verify(out, overlay, unit=False)
    paths = list(overlay.glob("*.v")) + [Path(__file__)] + list(out.glob("*reference.v")) + list(out.glob("*tb.sv"))
    (out / (args.mode + "-sources.json")).write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, indent=2) + "\n")


if __name__ == "__main__": main()
