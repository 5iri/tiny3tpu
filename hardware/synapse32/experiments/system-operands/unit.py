#!/usr/bin/env python3
"""Compare the actual registered-operand ALU overlay at the minimum CPU gap."""
import argparse
from pathlib import Path
import subprocess


def verify(out):
    here=Path(__file__).resolve().parent
    root=here.parents[3]
    tb=(here.parent/"shared-mul/alu_tb.sv").read_text()
    tb=tb.replace("    reg [31:0] a, b, imm, div_result, pc;",'''    reg [31:0] a, b, imm, div_result, pc;
    reg clk=0,rst=1;
    always #5 clk=~clk;
    reg [31:0] a_q,b_q;
    always @(posedge clk) begin
        if(rst) begin a_q<=0;b_q<=0;end
        else begin a_q<=a;b_q<=b;end
    end''')
    tb=tb.replace("alu candidate(.rs1(a),.rs2(b)",
        "alu #(.SYSTEM_MUL(1)) candidate(.system_clk(clk),.system_rst(rst),.rs1(a_q),.rs2(b_q)")
    tb=tb.replace("            #1;", "            repeat(3) @(posedge clk);\n            #1;")
    tb=tb.replace("            checked = checked + 1;", "            checked = checked + 1;\n            @(negedge clk);")
    tb=tb.replace("        imm=0; div_result=0; pc=0;", "        imm=0; div_result=0; pc=0;\n        repeat(4) @(negedge clk);rst=0;")
    tb=tb.replace("PASS shared combinational multiplier", "PASS registered-operand ALU at three system stages")
    path=out/"operand_alu_tb.sv";path.write_text(tb)
    commands=[(["iverilog","-g2012","-s","shared_mul_alu_tb","-I"+str(root.parent/"synapse32/rtl/include"),
                "-o",out/"operand-alu.vvp",out/"overlay/alu.v",out/"alu_reference.v",path],"operand-alu-compile.log"),
              (["vvp",out/"operand-alu.vvp"],"operand-alu.log")]
    for command,name in commands:
        with (out/name).open("w") as log:
            subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,check=True)
    print((out/"operand-alu.log").read_text(),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    verify(parser.parse_args().out.resolve())
