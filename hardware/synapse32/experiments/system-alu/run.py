#!/usr/bin/env python3
"""Register non-MUL ALU results during existing system-clock gaps."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
spec=importlib.util.spec_from_file_location("system_operands",HERE.parent/"system-operands/run.py")
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
run=base.base.run


def prepare(out):
    overlay=base.prepare(out)
    path=overlay/"execution_unit.v";ex=path.read_text()
    ex=ex.replace("exec_output = alu_inst.ALUoutput;","exec_output = alu_execute_result;")
    marker="// For all R-type instructions"
    registers='''// MUL already has a final system register at +3. Other ALU operations
// can use +2; DIV changes only at a CPU edge and is captured before consumption.
wire alu_is_mul = instr_id==INSTR_MUL || instr_id==INSTR_MULH ||
                  instr_id==INSTR_MULHSU || instr_id==INSTR_MULHU;
reg [31:0] alu_result_q;
always @(posedge system_clk) begin
    if(system_rst) alu_result_q<=0;
    else alu_result_q<=alu_inst.ALUoutput;
end
wire [31:0] alu_execute_result = SYSTEM_MUL && !alu_is_mul ? alu_result_q : alu_inst.ALUoutput;

'''
    path.write_text(ex.replace(marker,registers+marker,1))
    path=overlay/"riscv_cpu.v";cpu=path.read_text()
    start=cpu.index("    wire div_instruction =")
    end=cpu.index("    wire div_busy",start)
    expression=cpu[start:end].split("=",1)[1].strip().removesuffix(";")
    decode='''    wire div_instruction;
    synapse32_div_decode div_decode(
        .clk(clk),.rst(rst),.flush(pipeline_flush),.hold(pipeline_hold),.stall(hazard_stall),
        .valid_in(if_id_instr_valid_out),.instr_in(decoder_inst0_instr_id_out),.is_div(div_instruction));
`ifdef SYNAPSE32_FORWARD_ASSERT
    always @(negedge clk) if(!rst && div_instruction !== ('''+expression+'''))
        $fatal(1,"DIV decode lookahead mismatch");
`endif
'''
    cpu=cpu[:start]+decode+cpu[end:]
    marker="        wire signed [32:0] a_ref"
    check='''        always @(posedge clk) if(!rst && id_ex_inst0_instr_valid_out && !ex_unit_inst0.alu_is_mul) begin
            if(ex_unit_inst0.alu_execute_result !== ex_unit_inst0.alu_inst.ALUoutput)
                $fatal(1,"Stale system ALU result pc=%h",id_ex_inst0_pc_out);
        end
'''
    cpu=cpu.replace(marker,check+marker)
    path.write_text(cpu+'\n'+(HERE/"div_decode.v").read_text())
    return overlay


def prove(out):
    harness='''`include "instr_defines.vh"
module div_decode_equiv(input wire clk,rst,flush,hold,stall,valid_in,
    input wire [6:0] instr_in, output wire same);
wire valid_out,is_div;wire [6:0] instr_out;
synapse32_div_decode candidate(.*);
ID_EX reference(.clk(clk),.rst(rst),.flush(flush),.hold(hold),.stall(stall),
    .instr_valid_in(valid_in),.instr_id_in(instr_in),.instr_valid_out(valid_out),.instr_id_out(instr_out),
    .rs1_valid_in(1'b0),.rs2_valid_in(1'b0),.rd_valid_in(1'b0),.imm_in(32'b0),
    .rs1_addr_in(5'b0),.rs2_addr_in(5'b0),.rd_addr_in(5'b0),.opcode_in(7'b0),
    .pc_in(32'b0),.rs1_value_in(32'b0),.rs2_value_in(32'b0),.instr_page_fault_in(1'b0));
assign same=is_div==(valid_out && (instr_out==INSTR_DIV || instr_out==INSTR_DIVU ||
                                 instr_out==INSTR_REM || instr_out==INSTR_REMU));
endmodule
'''
    (out/"div-decode-equiv.v").write_text(harness)
    source=ROOT.parent/"synapse32"
    script="read_verilog -sv -I"+str(source/"rtl/include")+" "+str(HERE/"div_decode.v")+" "+str(source/"rtl/pipeline_stages/ID_EX.v")+" "+str(out/"div-decode-equiv.v")+"\n"
    script+="prep -top div_decode_equiv; flatten; async2sync; opt; check -assert; sat -seq 3 -tempinduct -set-init-zero -prove same 1 -verify;\n"
    (out/"div-decode.ys").write_text(script)
    run(["/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys","-Q","-T","-s",out/"div-decode.ys"],out/"div-decode-proof.log")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("prepare","prove","verify"))
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    overlay=prepare(out)
    if args.mode in ("prove","verify"):prove(out)
    if args.mode=="verify":
        base.verify_alu(out)
        base.base.verify(out,overlay,unit=False)
    paths=list(overlay.glob("*.v"))+list(HERE.glob("*.py"))+list(HERE.glob("*.v"))
    (out/(args.mode+"-sources.json")).write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')


if __name__=="__main__":main()
