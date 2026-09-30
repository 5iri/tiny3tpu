#!/usr/bin/env python3
"""Materialize a multiplier candidate on top of registered forwarding controls."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = HERE.parent / "divider"


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prepare(out, registered_divider=False):
    spec = importlib.util.spec_from_file_location("retime", HERE.parent / "forward-retime/run.py")
    retime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retime)
    overlay = retime.prepare(out)
    cpu = (overlay / "riscv_cpu.v").read_text()
    # Keep divider observation points intact for its existing tests.
    cpu = cpu.replace("!div_wait &&", "!execute_wait &&")
    cpu = cpu.replace("= div_wait || wfi_stall", "= execute_wait || wfi_stall")
    cpu = cpu.replace("(div_wait || mem_stage_page_fault_taken", "(execute_wait || mem_stage_page_fault_taken")
    marker = "    wire mem_stage_page_fault_taken;"
    addition = """    wire mul_instruction = id_ex_inst0_instr_valid_out &&
        ((id_ex_inst0_instr_id_out == INSTR_MUL) ||
         (id_ex_inst0_instr_id_out == INSTR_MULH) ||
         (id_ex_inst0_instr_id_out == INSTR_MULHSU) ||
         (id_ex_inst0_instr_id_out == INSTR_MULHU));
    wire mul_busy, mul_done;
    wire [31:0] mul_result;
    wire mul_wait = mul_instruction && !mul_done;
    wire execute_wait = div_wait || mul_wait;
    wire mul_start = mul_instruction && !mul_busy && !mul_done &&
                     !pipeline_flush && !wfi_stall &&
                     !store_buf_busy_stall && !fence_drain_stall;
    wire [1:0] mul_kind = id_ex_inst0_instr_id_out == INSTR_MUL ? 2'd0 :
                          id_ex_inst0_instr_id_out == INSTR_MULH ? 2'd1 :
                          id_ex_inst0_instr_id_out == INSTR_MULHSU ? 2'd2 : 2'd3;
    synapse32_multiply multiplier_inst (
        .clk(clk), .rst(rst), .cancel(pipeline_flush), .start(mul_start),
        .kind(mul_kind), .operand_a(ex_inst0_rs1_value_out),
        .operand_b(ex_inst0_rs2_value_out),
        .busy(mul_busy), .done(mul_done), .result(mul_result)
    );
"""
    cpu = replace_once(cpu, marker, addition + marker)
    cpu = replace_once(cpu, ".div_result(div_result),", ".div_result(div_result), .mul_result(mul_result),")
    cpu += "\n" + (HERE / "multiply.sv").read_text()
    (overlay / "riscv_cpu.v").write_text(cpu)
    ex = (overlay / "execution_unit.v").read_text()
    ex = replace_once(ex, "    input wire [31:0] div_result,", "    input wire [31:0] div_result, mul_result,")
    ex = replace_once(ex, ".div_result(div_result),", ".div_result(div_result), .mul_result(mul_result),")
    (overlay / "execution_unit.v").write_text(ex)
    alu = (overlay / "alu.v").read_text()
    alu = replace_once(alu, "    input wire [31:0] div_result,", "    input wire [31:0] div_result, mul_result,")
    start, end = alu.index("wire signed [31:0] rs1_signed"), alu.index("`ifdef FORMAL")
    alu = alu[:start] + alu[end:]
    for old in ("mul_signed[31:0]", "mul_signed[63:32]", "mul_mixed[63:32]", "mul_unsigned[63:32]"):
        alu = replace_once(alu, old, "mul_result")
    (overlay / "alu.v").write_text(alu)
    if registered_divider:
        (overlay / "divider.v").write_bytes((HERE / "divider_registered.v").read_bytes())
    sources = [HERE / "multiply.sv", Path(__file__), HERE.parent / "forward-retime/run.py"]
    sources += list(overlay.glob("*.v"))
    (out / "overlay-sources.json").write_text(json.dumps(
        {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}, indent=2) + "\n")
    return overlay


def divider_benches(out):
    target=out/"divider-tests"
    target.mkdir(exist_ok=True)
    cpu_test=(BASE/"cpu_tb.sv").read_text().replace(
        "wait(cpu.div_busy);", "wait(cpu.div_busy && !cpu.divider_inst.setup_q);")
    (target/"cpu_tb.sv").write_text(cpu_test)
    collision=(BASE/"cpu_collision_tb.sv").read_text()
    collision=replace_once(collision,
        "cpu.id_ex_inst0_pc_out==target_pc && !cpu.div_busy && !cpu.div_done",
        "cpu.id_ex_inst0_pc_out==target_pc && cpu.div_busy && cpu.divider_inst.setup_q")
    (target/"cpu_collision_tb.sv").write_text(collision)
    unit=(BASE/"divider_tb.sv").read_text().replace("cycles>=32","cycles>=33")
    unit=unit.replace("?0:32)","?1:33)").replace("i<33","i<34").replace("repeat(34)","repeat(35)")
    unit=unit.replace("cancel-boundaries=33","cancel-boundaries=34")
    (target/"divider_tb.sv").write_text(unit)
    return target


REFERENCE = """    function automatic [31:0] reference_div(input [31:0] a,b,input integer op);
        reg signed [63:0] sa,sb,product;
        begin
            sa = (op==1 || op==2) ? {{32{a[31]}},a} : {32'b0,a};
            sb = op==1 ? {{32{b[31]}},b} : {32'b0,b};
            product=sa*sb;
            reference_div=op==0 ? product[31:0] : product[63:32];
        end
    endfunction
"""


def benches(out):
    for name in ("cpu_tb", "cpu_collision_tb"):
        tb = (BASE / (name + ".sv")).read_text()
        tb = replace_once(tb, "module " + name + ";", "module " + name.replace("cpu", "cpu_mul") + ";")
        start = tb.index("    function automatic [31:0] reference_div")
        end = tb.index("    endfunction", start) + len("    endfunction\n")
        tb = tb[:start] + REFERENCE + tb[end:]
        for signal in ("wait", "instruction", "busy", "done", "start"):
            tb = tb.replace("cpu.div_" + signal, "cpu.mul_" + signal)
        # A flushed fetch slot can carry its old PC on a decoded ADDI x0 bubble.
        # Count actual MUL writebacks, including MUL rd=x0, rather than treating
        # every write-valid bubble with a matching PC as an arithmetic result.
        tb = tb.replace("cpu.mem_wb_inst0_rd_valid_out) begin", """cpu.mem_wb_inst0_rd_valid_out &&
               (cpu.mem_wb_inst0_instr_id_out == INSTR_MUL ||
                cpu.mem_wb_inst0_instr_id_out == INSTR_MULH ||
                cpu.mem_wb_inst0_instr_id_out == INSTR_MULHSU ||
                cpu.mem_wb_inst0_instr_id_out == INSTR_MULHU)) begin""")
        if name == "cpu_tb":
            tb = tb.replace("for(k=4;k<8;k=k+1)", "for(k=0;k<4;k=k+1)")
            tb = tb.replace("divide(k,k,1,2)", "divide(k,k+4,1,2)")
            tb = tb.replace("save(k);", "save(k+4);")
            for old,new in (("divide(4,", "divide(0,"), ("divide(5,", "divide(1,"),
                            ("divide(6,", "divide(2,"), ("divide(7,", "divide(3,"),
                            ("divide(4+(i%4),", "divide(i%4,")):
                tb = tb.replace(old,new)
            tb = tb.replace("32'h0220c1b3", "32'h022081b3")
            tb = tb.replace("repeat(5) @(negedge cpu_clk)", "repeat(1) @(negedge cpu_clk)")
        else:
            start = tb.index("            if((phase==0 &&")
            end = tb.index("                timer_irq=1;", start)
            tb = tb[:start] + """            if((phase==0 && cpu.id_ex_inst0_instr_valid_out &&
                           cpu.id_ex_inst0_pc_out==load_pc) ||
               (phase==1 && cpu.mul_busy && cpu.multiplier_inst.stage_q==3) ||
               (phase==2 && cpu.mul_busy && cpu.multiplier_inst.stage_q==4)) begin
""" + tb[end:]
            tb = tb.replace("cpu.divider_inst.count_q!=31", "cpu.multiplier_inst.stage_q!=4")
            tb = tb.replace("for(o=4;o<8;o=o+1)", "for(o=0;o<4;o=o+1)")
            tb = tb.replace("if(s!=2 || o==4 || o==6)", "if(1)")
            tb = tb.replace("if(s==0 || p!=1) run_case", "run_case")
            tb = tb.replace("case_count!=64 || irq_cases!=24 || fault_cases!=40", "case_count!=84 || irq_cases!=36 || fault_cases!=48")
            tb = tb.replace("stores=256", "stores=336")
        (out / (name.replace("cpu", "cpu_mul") + ".sv")).write_text(tb)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(prepare(out))
    benches(out)
