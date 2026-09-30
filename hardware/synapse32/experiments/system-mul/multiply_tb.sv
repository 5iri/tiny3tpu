`timescale 1ns/1ps
`include "instr_defines.vh"
module system_mul_tb;
    reg clk=0,rst=1;
    always #5 clk=~clk;
    reg [31:0] a=0,b=0;
    reg [6:0] instr_id=0;
    wire [31:0] result;
    synapse32_system_multiply dut(.*);
    reg [31:0] expected[0:2];
    reg valid[0:2];
    reg signed [32:0] sa,sb;
    reg signed [65:0] prod;
    reg [31:0] corners[0:9];
    integer checked=0,i,j,op;
    always @(posedge clk) begin
        if(rst) begin
            for(integer k=0;k<3;k=k+1) begin expected[k]=0;valid[k]=0;end
        end else begin
            expected[2]=expected[1];expected[1]=expected[0];
            valid[2]=valid[1];valid[1]=valid[0];valid[0]=1;
            sa=$signed({a[31]&&(instr_id==INSTR_MULH||instr_id==INSTR_MULHSU),a});
            sb=$signed({b[31]&&instr_id==INSTR_MULH,b}); prod=sa*sb;
            expected[0]=instr_id==INSTR_MUL?prod[31:0]:prod[63:32];
            #1;
            if(valid[2]) begin
                if(result!==expected[2]) $fatal(1,"product %h != %h",result,expected[2]);
                checked=checked+1;
            end
        end
    end
    task issue(input [31:0] x,y,input integer kind);
        @(negedge clk);
        a=x;b=y;
        case(kind)
            0:instr_id=INSTR_MUL; 1:instr_id=INSTR_MULH;
            2:instr_id=INSTR_MULHSU; 3:instr_id=INSTR_MULHU;
        endcase
    endtask
    initial begin
        corners[0]=0;corners[1]=1;corners[2]=32'hffffffff;
        corners[3]=32'h80000000;corners[4]=32'h7fffffff;
        corners[5]=32'hffff;corners[6]=32'h10000;
        corners[7]=32'hffff0000;corners[8]=32'h80008000;corners[9]=32'h5555aaaa;
        repeat(3) @(negedge clk);rst=0;
        for(op=0;op<4;op=op+1) for(i=0;i<10;i=i+1) for(j=0;j<10;j=j+1)
            issue(corners[i],corners[j],op);
        for(i=0;i<100000;i=i+1) begin
            issue($random,$random,i%4);
            if(i%7919==0) begin
                @(negedge clk);rst=1;
                @(negedge clk);rst=0;
            end
        end
        repeat(4) @(negedge clk);
        $display("PASS system multiply %0d pipelined products, mixed signedness and reset",checked);
        $finish;
    end
endmodule
