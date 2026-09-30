#!/usr/bin/env python3
"""Pipeline MUL in existing gaps between enabled CPU edges; default CPU unchanged."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
spec=importlib.util.spec_from_file_location("shared_mul",HERE.parent/"shared-mul/run.py")
shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
run=shared.retime.run


def prepare(out):
    overlay=shared.prepare(out)
    cpu=(overlay/"riscv_cpu.v").read_text()
    cpu=cpu.replace("module riscv_cpu (", "module riscv_cpu #(parameter SYSTEM_MUL=0) (\n    input wire system_clk,")
    cpu=cpu.replace("execution_unit ex_unit_inst0 (", "execution_unit #(.SYSTEM_MUL(SYSTEM_MUL)) ex_unit_inst0 (\n        .system_clk(system_clk), .system_rst(rst),")
    check='''
`ifdef SYNAPSE32_SYSTEM_MUL_ASSERT
    if (SYSTEM_MUL) begin : check_system_mul
        // Compare the value about to enter EX/MEM against current, unregistered
        // forwarded operands. This catches stale operands and insufficient gaps.
        wire signed [32:0] a_ref = $signed({ex_inst0_rs1_value_out[31] &&
            (id_ex_inst0_instr_id_out==INSTR_MULH || id_ex_inst0_instr_id_out==INSTR_MULHSU), ex_inst0_rs1_value_out});
        wire signed [32:0] b_ref = $signed({ex_inst0_rs2_value_out[31] &&
            id_ex_inst0_instr_id_out==INSTR_MULH, ex_inst0_rs2_value_out});
        wire signed [65:0] product_ref = a_ref*b_ref;
        always @(posedge clk) if (!rst && id_ex_inst0_instr_valid_out &&
            (id_ex_inst0_instr_id_out==INSTR_MUL || id_ex_inst0_instr_id_out==INSTR_MULH ||
             id_ex_inst0_instr_id_out==INSTR_MULHSU || id_ex_inst0_instr_id_out==INSTR_MULHU)) begin
            if (ex_unit_inst0.alu_inst.ALUoutput !==
                (id_ex_inst0_instr_id_out==INSTR_MUL ? product_ref[31:0] : product_ref[63:32]))
                $fatal(1,"System-clock multiply was not ready at CPU edge pc=%h",id_ex_inst0_pc_out);
        end
    end
`endif
'''
    cpu=cpu.replace("endmodule",check+"endmodule",1)
    (overlay/"riscv_cpu.v").write_text(cpu)
    ex=(overlay/"execution_unit.v").read_text()
    ex=ex.replace("module execution_unit(","module execution_unit #(parameter SYSTEM_MUL=0)(\n    input wire system_clk, system_rst,")
    ex=ex.replace("alu alu_inst(","alu #(.SYSTEM_MUL(SYSTEM_MUL)) alu_inst(\n    .system_clk(system_clk), .system_rst(system_rst),")
    (overlay/"execution_unit.v").write_text(ex)
    alu=(overlay/"alu.v").read_text()
    alu=alu.replace("module alu (","module alu #(parameter SYSTEM_MUL=0) (\n    input wire system_clk, system_rst,")
    start=alu.index("// One signed 33-bit product")
    end=alu.index("wire div_by_zero",start)
    product=alu[start:end]
    alu=alu[:start]+'''wire [31:0] multiply_result;
generate if (SYSTEM_MUL) begin : system_multiply
    synapse32_system_multiply pipe(.clk(system_clk), .rst(system_rst),
        .a(rs1), .b(rs2), .instr_id(instr_id), .result(multiply_result));
end else begin : combinational_multiply
'''+product+'''    assign multiply_result = instr_id==INSTR_MUL ? mul_product[31:0] : mul_product[63:32];
end endgenerate
'''+alu[end:]
    alu=alu.replace("ALUoutput = mul_product[31:0]","ALUoutput = multiply_result").replace("ALUoutput = mul_product[63:32]","ALUoutput = multiply_result")
    (overlay/"alu.v").write_text(alu+'\n'+(HERE/"multiply.v").read_text())
    return overlay


def verify(out,overlay,unit=True):
    source=ROOT.parent/"synapse32"
    if unit:
        run(["iverilog","-g2012","-s","system_mul_tb","-I"+str(source/"rtl/include"),
             "-o",out/"unit.vvp",HERE/"multiply.v",HERE/"multiply_tb.sv"],out/"unit-compile.log")
        run(["vvp",out/"unit.vvp"],out/"unit.log");print((out/"unit.log").read_text(),flush=True)
    files=[overlay/n for n in ("riscv_cpu.v","execution_unit.v","alu.v","divider.v")]
    files += [source/"rtl"/n for n in ("memory_unit.v","writeback.v")]
    files += [p for d in ("core_modules","pipeline_stages") for p in sorted((source/"rtl"/d).glob("*.v")) if p.name not in ("alu.v","divider.v")]
    for bench in ("cpu_tb","cpu_collision_tb"):
        tb=(HERE.parent/"divider"/(bench+".sv")).read_text()
        tb=tb.replace("riscv_cpu cpu (","riscv_cpu #(.SYSTEM_MUL(GATED)) cpu (\n        .system_clk(clk),")
        (out/(bench+".sv")).write_text(tb)
        for gated in (0,1):
            tag=f"{bench}-gated{gated}";obj=out/("obj-"+tag)
            run(["verilator","--binary","--timing","-j","2","-Wno-fatal","--top-module",bench,
                 f"-GGATED={gated}","--Mdir",obj,"-DSYNAPSE32_CLOCK_SIM","-DSYNAPSE32_FORWARD_ASSERT",
                 "-DSYNAPSE32_SYSTEM_MUL_ASSERT","-I"+str(source/"rtl/include"),*files,
                 ROOT/"hardware/synapse32/synapse32_memory_sequencer.sv",
                 ROOT/"hardware/synapse32/synapse32_clock_enable.sv",out/(bench+".sv")],out/(tag+"-compile.log"))
            run([obj/("V"+bench)],out/(tag+".log"));print((out/(tag+".log")).read_text(),flush=True)
    run([sys.executable,HERE.parent/"mul-pipeline/benchmark.py","--out",out/"ipc",
         "--baseline",ROOT/"build-ddr-shared-mul","--candidate",out,"--candidate-system-mul"],out/"ipc.log")
    print((out/"ipc.log").read_text(),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("prepare","verify"))
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    overlay=prepare(out);source=ROOT.parent/"synapse32"
    if args.mode=="verify":
        verify(out,overlay)
    paths=list(overlay.glob("*.v"))+list(HERE.glob("*.py"))+list(HERE.glob("*.v"))+list(HERE.glob("*.sv"))
    (out/(args.mode+"-sources.json")).write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')


if __name__=="__main__":main()
