`timescale 1ns/1ps
`include "instr_defines.vh"
module forward_lookahead_tb;
    reg clk=0, rst=1;
    always #5 clk=~clk;
    reg flush=0, hold=0, stall=0, ex_mem_flush=0, mem_page_fault=0;
    reg [4:0] id_rs1=0,id_rs2=0,id_rd=0;
    reg id_rs1_valid=0,id_rs2_valid=0,id_rd_valid=0;
    reg [6:0] id_instr=INSTR_ADDI;
    wire [4:0] ex_rs1,ex_rs2,ex_rd,mem_rd,wb_rd;
    wire ex_rs1_valid,ex_rs2_valid,ex_rd_valid,mem_rd_valid,wb_rd_valid;
    wire [6:0] ex_instr,mem_instr;
    wire [1:0] gold_a,gold_b,got_a,got_b;
    integer checks=0, hold_changes=0, mem_hits=0, wb_hits=0;
    reg [1:0] previous_a, previous_b;
    reg [31:0] rng=32'h709ac153;
    function automatic [31:0] random_word(input [31:0] x);
        reg [31:0] t;
        begin t=x^(x<<13); t=t^(t>>17); random_word=t^(t<<5); end
    endfunction
    ID_EX ex_reg (
        .clk(clk),.rst(rst),.flush(flush),.hold(hold),.stall(stall),
        .rs1_addr_in(id_rs1),.rs2_addr_in(id_rs2),.rd_addr_in(id_rd),
        .rs1_valid_in(id_rs1_valid),.rs2_valid_in(id_rs2_valid),.rd_valid_in(id_rd_valid),
        .instr_id_in(id_instr),.imm_in(32'b0),.opcode_in(7'b0010011),
        .pc_in(32'b0),.rs1_value_in(32'b0),.rs2_value_in(32'b0),
        .instr_valid_in(1'b1),.instr_page_fault_in(1'b0),
        .rs1_addr_out(ex_rs1),.rs2_addr_out(ex_rs2),.rd_addr_out(ex_rd),
        .rs1_valid_out(ex_rs1_valid),.rs2_valid_out(ex_rs2_valid),
        .rd_valid_out(ex_rd_valid),.instr_id_out(ex_instr)
    );
    EX_MEM mem_reg (
        .clk(clk),.rst(rst),.flush(ex_mem_flush),
        .rs1_addr_in(5'b0),.rs2_addr_in(5'b0),.rd_addr_in(ex_rd),
        .rs1_value_in(32'b0),.rs2_value_in(32'b0),.pc_in(32'b0),
        .mem_addr_in(32'b0),.exec_output_in(32'b0),
        .jump_signal_in(1'b0),.jump_addr_in(32'b0),
        .instr_id_in(ex_instr),.rd_valid_in(ex_rd_valid),
        .rd_addr_out(mem_rd),.rd_valid_out(mem_rd_valid),.instr_id_out(mem_instr)
    );
    MEM_WB wb_reg (
        .clk(clk),.rst(rst),.flush(1'b0),
        .rs1_addr_in(5'b0),.rs2_addr_in(5'b0),.rd_addr_in(mem_rd),
        .rs1_value_in(32'b0),.rs2_value_in(32'b0),.pc_in(32'b0),
        .mem_addr_in(32'b0),.exec_output_in(32'b0),.mem_data_in(32'b0),
        .jump_signal_in(1'b0),.jump_addr_in(32'b0),
        .instr_id_in(mem_page_fault ? 7'b0 : mem_instr),
        .rd_valid_in(!mem_page_fault && mem_rd_valid),
        .rd_addr_out(wb_rd),.rd_valid_out(wb_rd_valid)
    );
    forwarding_unit gold (
        .rs1_addr_ex(ex_rs1),.rs2_addr_ex(ex_rs2),
        .rs1_valid_ex(ex_rs1_valid),.rs2_valid_ex(ex_rs2_valid),
        .rd_addr_mem(mem_rd),.rd_valid_mem(mem_rd_valid),.instr_id_mem(mem_instr),
        .rd_addr_wb(wb_rd),.rd_valid_wb(wb_rd_valid),.wr_en_wb(wb_rd_valid),
        .forward_a(gold_a),.forward_b(gold_b)
    );
    forward_lookahead dut (
        .clk(clk),.rst(rst),.flush(flush),.hold(hold),.stall(stall),
        .ex_mem_flush(ex_mem_flush),.mem_page_fault(mem_page_fault),
        .id_rs1(id_rs1),.id_rs2(id_rs2),.id_rs1_valid(id_rs1_valid),.id_rs2_valid(id_rs2_valid),
        .ex_rs1(ex_rs1),.ex_rs2(ex_rs2),.ex_rd(ex_rd),
        .ex_rs1_valid(ex_rs1_valid),.ex_rs2_valid(ex_rs2_valid),.ex_rd_valid(ex_rd_valid),
        .ex_instr(ex_instr),.mem_rd(mem_rd),.mem_rd_valid(mem_rd_valid),
        .forward_a_q(got_a),.forward_b_q(got_b)
    );
    task tick;
        begin
            previous_a=gold_a; previous_b=gold_b;
            @(posedge clk); #1;
            if ({gold_a,gold_b} !== {got_a,got_b})
                $fatal(1,"selector mismatch check=%0d gold=%b/%b got=%b/%b", checks,gold_a,gold_b,got_a,got_b);
            checks=checks+1;
            if (hold && !flush && !rst && {gold_a,gold_b}!={previous_a,previous_b}) hold_changes=hold_changes+1;
            if (gold_a==1 || gold_b==1) mem_hits=mem_hits+1;
            if (gold_a==2 || gold_b==2) wb_hits=wb_hits+1;
            @(negedge clk);
        end
    endtask
    initial begin
        tick(); rst=0;
        // A producer followed by a dependent divide: selector MEM -> WB -> RF
        // as older stages drain. Holding a precomputed selector is incorrect.
        id_rd=5; id_rd_valid=1; tick();
        id_instr=INSTR_DIV; id_rd=6; id_rs1=5; id_rs1_valid=1; tick();
        hold=1; ex_mem_flush=1; tick(); tick(); tick();
        flush=1; stall=1; tick();
        // Every possible producer instruction ID, two matching producers,
        // both source operands, and x0. Exercises MEM priority and load-class
        // exclusion even in tag combinations that real issue would interlock.
        for (integer op=0;op<128;op=op+1) begin
            rst=1; tick(); rst=0;
            flush=0; hold=0; stall=0; ex_mem_flush=0; mem_page_fault=0;
            id_rd=5; id_rd_valid=1; id_rs1_valid=0; id_rs2_valid=0;
            id_instr=INSTR_ADDI; tick();
            id_instr=op[6:0]; tick();
            id_instr=INSTR_ADD; id_rs1=5; id_rs2=5;
            id_rs1_valid=1; id_rs2_valid=1; tick();
            id_rd=0; id_rs1=0; id_rs2=0; tick(); tick();
        end
        // Arbitrary controls include unreachable states: stronger local check,
        // but this is a dynamic selector test, not whole-CPU formal equivalence.
        for (integer i=0;i<30000;i=i+1) begin
            rng=random_word(rng);
            {flush,hold,stall,ex_mem_flush,mem_page_fault}=rng[4:0];
            rst=(i%997==0);
            id_rs1=rng[9:5]; id_rs2=rng[14:10]; id_rd=rng[19:15];
            {id_rs1_valid,id_rs2_valid,id_rd_valid}=rng[22:20];
            id_instr=rng[29:23];
            // Frequent RAW/WAW matches including x0 and every 7-bit instr ID.
            if (i%3==0) id_rs1=ex_rd;
            if (i%5==0) id_rs2=mem_rd;
            tick();
        end
        if (hold_changes<2 || mem_hits==0 || wb_hits==0) $fatal(1,"coverage missing");
        $display("PASS checks=%0d held-selector-changes=%0d MEM-hit-edges=%0d WB-hit-edges=%0d",checks,hold_changes,mem_hits,wb_hits);
        $finish;
    end
endmodule
