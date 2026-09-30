#!/usr/bin/env python3
"""Precompute CSR interrupt eligibility while keeping pending interrupts live."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
spec=importlib.util.spec_from_file_location("mul_select",HERE.parent/"system-mul-select/run.py")
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


def prepare(out):
    overlay=base.prepare(out)
    original=(ROOT.parent/"synapse32/rtl/core_modules/interrupt_controller.v").read_text()
    (out/"interrupt_reference.v").write_text(original.replace("module interrupt_controller (","module interrupt_reference ("))
    source=original.replace("module interrupt_controller (","module synapse32_irq_enable #(parameter SYSTEM_MUL=0) (\n    input wire system_clk,")
    start=source.index("    always @(*) begin")
    source=source[:start]+'''    // Only CSR-derived eligibility is staged. MIP remains live so a late
    // external/software/timer pending transition is visible at the CPU edge.
    wire [5:0] enables_raw = {
        meie && m_interrupts_enabled, msie && m_interrupts_enabled,
        mtie && m_interrupts_enabled, seie && mideleg[9] && s_interrupts_enabled,
        ssie && mideleg[1] && s_interrupts_enabled, stie && mideleg[5] && s_interrupts_enabled};
    reg [5:0] enables_q;
    always @(posedge system_clk) begin
        if(rst) enables_q<=0;
        else enables_q<=enables_raw;
    end
    wire [5:0] enables = SYSTEM_MUL ? enables_q : enables_raw;
    always_comb begin
        interrupt_pending=0;
        interrupt_cause=0;
        interrupt_to_supervisor=0;
        interrupt_pc=current_pc;
        if(enables[5] && meip) begin
            interrupt_pending=1;interrupt_cause=MACHINE_EXTERNAL_INTERRUPT;
        end else if(enables[4] && msip) begin
            interrupt_pending=1;interrupt_cause=MACHINE_SOFTWARE_INTERRUPT;
        end else if(enables[3] && mtip) begin
            interrupt_pending=1;interrupt_cause=MACHINE_TIMER_INTERRUPT;
        end else if(enables[2] && seip) begin
            interrupt_pending=1;interrupt_cause=SUPERVISOR_EXTERNAL_INTERRUPT;interrupt_to_supervisor=1;
        end else if(enables[1] && ssip) begin
            interrupt_pending=1;interrupt_cause=SUPERVISOR_SOFTWARE_INTERRUPT;interrupt_to_supervisor=1;
        end else if(enables[0] && stip) begin
            interrupt_pending=1;interrupt_cause=SUPERVISOR_TIMER_INTERRUPT;interrupt_to_supervisor=1;
        end
    end
endmodule
'''
    (out/"interrupt_candidate.v").write_text(source)
    path=overlay/"riscv_cpu.v";cpu=path.read_text()
    marker="interrupt_controller int_ctrl_inst ("
    assert cpu.count(marker)==1
    cpu=cpu.replace(marker,"synapse32_irq_enable #(.SYSTEM_MUL(SYSTEM_MUL)) int_ctrl_inst (\n        .system_clk(system_clk),",1)
    marker="        wire signed [32:0] a_ref"
    check='''        always @(posedge clk) if(!rst) begin
            if(int_ctrl_inst.enables !== int_ctrl_inst.enables_raw)
                $fatal(1,"Stale IRQ eligibility at CPU edge");
        end
'''
    assert marker in cpu
    cpu=cpu.replace(marker,check+marker,1)
    path.write_text(cpu+"\n"+source)
    return overlay


def verify_irq(out):
    tb='''module irq_enable_tb;
reg clk=0,rst=1;
always #5 clk=~clk;
reg [31:0] mstatus=0,mie=0,mip=0,mideleg=0,current_pc=0;
reg [1:0] privilege_mode=0;
wire gold_pending,gold_super;wire [31:0] gold_cause,gold_pc;
wire [1:0] gate_pending,gate_super;wire [31:0] gate_cause[0:1],gate_pc[0:1];
interrupt_reference gold(.clk(clk),.rst(rst),.timer_interrupt(1'b0),.software_interrupt(1'b0),.external_interrupt(1'b0),
 .mstatus(mstatus),.mie(mie),.mip(mip),.mideleg(mideleg),.privilege_mode(privilege_mode),
 .interrupt_pending(gold_pending),.interrupt_cause(gold_cause),.interrupt_to_supervisor(gold_super),
 .interrupt_taken(1'b0),.current_pc(current_pc),.interrupt_pc(gold_pc));
generate for(genvar g=0;g<2;g=g+1) begin
synapse32_irq_enable #(.SYSTEM_MUL(g)) gate(.system_clk(clk),.clk(clk),.rst(rst),.timer_interrupt(1'b0),.software_interrupt(1'b0),.external_interrupt(1'b0),
 .mstatus(mstatus),.mie(mie),.mip(mip),.mideleg(mideleg),.privilege_mode(privilege_mode),
 .interrupt_pending(gate_pending[g]),.interrupt_cause(gate_cause[g]),.interrupt_to_supervisor(gate_super[g]),
 .interrupt_taken(1'b0),.current_pc(current_pc),.interrupt_pc(gate_pc[g]));
end endgenerate
integer config_id,pending_id,g,checks=0;
initial begin
repeat(2) @(negedge clk);rst=0;
for(config_id=0;config_id<8192;config_id=config_id+1) begin
 {mie[11],mie[3],mie[7],mie[9],mie[1],mie[5]}=config_id[5:0];
 {mideleg[9],mideleg[1],mideleg[5]}=config_id[8:6];
 privilege_mode=config_id[10:9];{mstatus[3],mstatus[1]}=config_id[12:11];
 @(posedge clk);#1;
 for(pending_id=0;pending_id<64;pending_id=pending_id+1) begin
  {mip[11],mip[3],mip[7],mip[9],mip[1],mip[5]}=pending_id[5:0];
  current_pc=config_id*32'h9e3779b9+pending_id;#1;
  for(g=0;g<2;g=g+1)
   if({gold_pending,gold_cause,gold_super,gold_pc} !== {gate_pending[g],gate_cause[g],gate_super[g],gate_pc[g]})
    $fatal(1,"IRQ eligibility mismatch mode=%d cfg=%d pending=%d gold=%h gate=%h",g,config_id,pending_id,{gold_pending,gold_cause,gold_super,gold_pc},{gate_pending[g],gate_cause[g],gate_super[g],gate_pc[g]});
  checks=checks+1;
 end
 @(negedge clk);
end
$display("PASS IRQ eligibility: %0d combinations in both modes, pending inputs remain live",checks);$finish;
end
endmodule
'''
    (out/"irq_enable_tb.sv").write_text(tb)
    run=base.base.validation.run
    run(["iverilog","-g2012","-s","irq_enable_tb","-o",out/"irq.vvp",out/"interrupt_reference.v",out/"interrupt_candidate.v",out/"irq_enable_tb.sv"],out/"irq-compile.log")
    run(["vvp",out/"irq.vvp"],out/"irq.log")
    print((out/"irq.log").read_text(),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("prepare","verify"));parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    overlay=prepare(out)
    if args.mode=="verify":
        verify_irq(out)
        base.base.validation.verify(out,overlay,unit=False)
    paths=list(overlay.glob("*.v"))+[Path(__file__)]+list(out.glob("interrupt*.v"))+list(out.glob("*tb.sv"))
    (out/(args.mode+"-sources.json")).write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+"\n")
