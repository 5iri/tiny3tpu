`default_nettype none
`include "instr_defines.vh"
// Decode in parallel with ID/EX, preserving its reset/flush/hold/stall priority.
module synapse32_div_decode (
    input wire clk,rst,flush,hold,stall,valid_in,
    input wire [6:0] instr_in,
    output reg is_div
);
    always @(posedge clk or posedge rst) begin
        if(rst) is_div<=0;
        else if(flush) is_div<=0;
        else if(hold) is_div<=is_div;
        else if(stall) is_div<=0;
        else is_div<=valid_in && (instr_in==INSTR_DIV || instr_in==INSTR_DIVU ||
                                 instr_in==INSTR_REM || instr_in==INSTR_REMU);
    end
endmodule
