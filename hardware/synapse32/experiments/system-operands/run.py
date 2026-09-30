#!/usr/bin/env python3
"""Capture forwarded operands in existing system-clock gaps, without CPU stalls."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
unit_spec=importlib.util.spec_from_file_location("system_operands_unit",HERE/"unit.py")
unit_module=importlib.util.module_from_spec(unit_spec);unit_spec.loader.exec_module(unit_module)
verify_alu=unit_module.verify
spec=importlib.util.spec_from_file_location("system_mul",HERE.parent/"system-mul/run.py")
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


def prepare(out):
    overlay=base.prepare(out)
    path=overlay/"execution_unit.v";ex=path.read_text()
    ex=ex.replace("reg [31:0] rs1_value;","reg [31:0] rs1_raw;\nwire [31:0] rs1_value;")
    ex=ex.replace("reg [31:0] rs2_value;","reg [31:0] rs2_raw;\nwire [31:0] rs2_value;")
    start=ex.index("    // Forward logic for rs1")
    end=ex.index("alu #(.SYSTEM_MUL",start)
    forwarding=ex[start:end].replace("rs1_value =", "rs1_raw =").replace("rs2_value =", "rs2_raw =")
    registers='''
generate if (SYSTEM_MUL) begin : system_operands
    reg [31:0] a_q,b_q;
    always @(posedge system_clk) begin
        if(system_rst) begin a_q<=0;b_q<=0;end
        else begin a_q<=rs1_raw;b_q<=rs2_raw;end
    end
    assign rs1_value=a_q;
    assign rs2_value=b_q;
end else begin : direct_operands
    assign rs1_value=rs1_raw;
    assign rs2_value=rs2_raw;
end endgenerate

'''
    path.write_text(ex[:start]+forwarding+registers+ex[end:])
    # Share the operand capture with all execution consumers. Remove the MUL
    # helper's redundant input stage so it remains ready at CPU edge +4.
    path=overlay/"alu.v";alu=path.read_text()
    start=alu.index("module synapse32_system_multiply")
    header=alu[:start];mul=alu[start:]
    a_hi="$signed({a[31] && (instr_id==INSTR_MULH || instr_id==INSTR_MULHSU),a[31:16]})"
    b_hi="$signed({b[31] && instr_id==INSTR_MULH,b[31:16]})"
    mul=mul.replace("p00<=a_lo*b_lo;","p00<=a[15:0]*b[15:0];")
    mul=mul.replace("p01<=$signed({1'b0,a_lo})*b_hi;", "p01<=$signed({1'b0,a[15:0]})*"+b_hi+";")
    mul=mul.replace("p10<=a_hi*$signed({1'b0,b_lo});", "p10<="+a_hi+"*$signed({1'b0,b[15:0]});")
    mul=mul.replace("p11<=a_hi*b_hi;", "p11<="+a_hi+"*"+b_hi+";")
    mul=mul.replace("low_s2<=low_s1;", "low_s2<=instr_id==INSTR_MUL;")
    # Dead stage-one registers are removed from the source, not just by synthesis.
    for line in ("    reg [15:0] a_lo, b_lo;\n","    reg signed [16:0] a_hi, b_hi;\n",
                 "            a_lo<=0; b_lo<=0; a_hi<=0; b_hi<=0;\n",
                 "            a_lo<=a[15:0]; b_lo<=b[15:0];\n",
                 "            a_hi<="+a_hi+";\n","            b_hi<="+b_hi+";\n",
                 "            low_s1<=instr_id==INSTR_MUL;\n"):
        assert line in mul,line
        mul=mul.replace(line,"")
    mul=mul.replace("reg low_s1, low_s2;","reg low_s2;").replace("low_s1<=0; low_s2<=0;","low_s2<=0;")
    path.write_text(header+mul)
    path=overlay/"riscv_cpu.v";cpu=path.read_text()
    marker="        wire signed [32:0] a_ref"
    check='''        always @(posedge clk) if(!rst) begin
            if(ex_inst0_rs1_value_out !== ex_unit_inst0.rs1_raw ||
               ex_inst0_rs2_value_out !== ex_unit_inst0.rs2_raw)
                $fatal(1,"Stale system operands at enabled CPU edge pc=%h",id_ex_inst0_pc_out);
        end
'''
    assert marker in cpu
    path.write_text(cpu.replace(marker,check+marker))
    return overlay


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("prepare","verify"))
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    overlay=prepare(out)
    if args.mode=="verify":
        verify_alu(out)
        base.verify(out,overlay,unit=False)
    paths=list(overlay.glob("*.v"))+[Path(__file__),HERE.parent/"system-mul/run.py",HERE.parent/"system-mul/multiply.v"]
    (out/(args.mode+"-sources.json")).write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')


if __name__=="__main__":main()
