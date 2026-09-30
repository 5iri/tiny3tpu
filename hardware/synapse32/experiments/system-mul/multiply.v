`default_nettype none
`include "instr_defines.vh"
// Three system-clock stages. The SoC must leave at least four system rising
// edges between enabled CPU rising edges. This adds no architectural stall.
// Keep branch, address, exception and non-MUL paths combinational: the memory
// sequencer samples their post-CPU-edge outputs on the very next system edge.
module synapse32_system_multiply (
    input wire clk, rst,
    input wire [31:0] a, b,
    input wire [6:0] instr_id,
    output reg [31:0] result
);
    reg [15:0] a_lo, b_lo;
    reg signed [16:0] a_hi, b_hi;
    reg low_s1, low_s2;
    reg [31:0] p00;
    reg signed [33:0] p01, p10, p11;
    wire signed [35:0] middle = {{2{p01[33]}},p01} +
                                {{2{p10[33]}},p10} + {20'b0,p00[31:16]};
    wire [31:0] high_word = p11[31:0] + {{12{middle[35]}},middle[35:16]};

    always @(posedge clk) begin
        if (rst) begin
            a_lo<=0; b_lo<=0; a_hi<=0; b_hi<=0;
            low_s1<=0; low_s2<=0;
            p00<=0; p01<=0; p10<=0; p11<=0; result<=0;
        end else begin
            a_lo<=a[15:0]; b_lo<=b[15:0];
            a_hi<=$signed({a[31] && (instr_id==INSTR_MULH || instr_id==INSTR_MULHSU),a[31:16]});
            b_hi<=$signed({b[31] && instr_id==INSTR_MULH,b[31:16]});
            low_s1<=instr_id==INSTR_MUL;
            p00<=a_lo*b_lo;
            p01<=$signed({1'b0,a_lo})*b_hi;
            p10<=a_hi*$signed({1'b0,b_lo});
            p11<=a_hi*b_hi;
            low_s2<=low_s1;
            result<=low_s2 ? {middle[15:0],p00[15:0]} : high_word;
        end
    end
endmodule
