`timescale 1ns/1ps
`include "instr_defines.vh"
module split_mul_alu_tb;
    reg [31:0] a, b, imm, div_result, pc;
    reg [6:0] instruction;
    wire [31:0] expected, actual;
    reg [31:0] corner [0:11];
    reg [31:0] random_state = 32'h17f0abcd;
    integer i, j, k, checked = 0;
    alu_reference gold(.rs1(a),.rs2(b),.imm(imm),.instr_id(instruction),
        .div_result(div_result),.pc_input(pc),.ALUoutput(expected));
    alu candidate(.rs1(a),.rs2(b),.imm(imm),.instr_id(instruction),
        .div_result(div_result),.pc_input(pc),.ALUoutput(actual));
    function automatic [31:0] random_word;
        begin
            random_state = random_state ^ (random_state << 13);
            random_state = random_state ^ (random_state >> 17);
            random_state = random_state ^ (random_state << 5);
            random_word = random_state;
        end
    endfunction
    task check;
        begin
            #1;
            if (actual !== expected)
                $fatal(1,"ALU op=%0d a=%h b=%h actual=%h expected=%h",
                       instruction,a,b,actual,expected);
            checked = checked + 1;
        end
    endtask
    initial begin
        corner[0]=0; corner[1]=1; corner[2]=32'hffffffff; corner[3]=32'h80000000;
        corner[4]=32'h7fffffff; corner[5]=32'h80000001; corner[6]=32'hffff;
        corner[7]=32'h10000; corner[8]=32'hffff0000; corner[9]=32'hffffffff-1;
        corner[10]=32'haaaaaaaa; corner[11]=32'h55555555;
        imm=0; div_result=0; pc=0;
        for (i=0;i<12;i=i+1) for (j=0;j<12;j=j+1) begin
            a=corner[i]; b=corner[j];
            instruction=INSTR_MUL; check();
            instruction=INSTR_MULH; check();
            instruction=INSTR_MULHSU; check();
            instruction=INSTR_MULHU; check();
        end
        // Exercise every opcode, including the unchanged ALU operations.
        for (i=0;i<4096;i=i+1) begin
            a=random_word(); b=random_word(); imm=random_word();
            div_result=random_word(); pc=random_word();
            for (k=0;k<128;k=k+1) begin instruction=k; check(); end
        end
        $display("PASS split cascade-free multiplier: %0d ALU comparisons",checked);
        $finish;
    end
endmodule
