// Control-only prototype, NOT a complete CPU overlay.
// Predict forwarding for the state AFTER the upcoming enabled CPU edge.
`include "instr_defines.vh"
module forward_lookahead (
    input wire clk, rst,
    input wire flush, hold, stall, ex_mem_flush, mem_page_fault,
    input wire [4:0] id_rs1, id_rs2,
    input wire id_rs1_valid, id_rs2_valid,
    input wire [4:0] ex_rs1, ex_rs2, ex_rd,
    input wire ex_rs1_valid, ex_rs2_valid, ex_rd_valid,
    input wire [6:0] ex_instr,
    input wire [4:0] mem_rd,
    input wire mem_rd_valid,
    output reg [1:0] forward_a_q, forward_b_q
);
    wire bubble = flush || (!hold && stall);
    wire [4:0] next_rs1 = hold ? ex_rs1 : id_rs1;
    wire [4:0] next_rs2 = hold ? ex_rs2 : id_rs2;
    wire next_v1 = !bubble && (hold ? ex_rs1_valid : id_rs1_valid);
    wire next_v2 = !bubble && (hold ? ex_rs2_valid : id_rs2_valid);
    wire next_mem_valid = !ex_mem_flush && ex_rd_valid;
    wire next_wb_valid = !mem_page_fault && mem_rd_valid;
    function automatic late_result(input [6:0] instr);
        case (instr)
            INSTR_LB, INSTR_LH, INSTR_LW, INSTR_LBU, INSTR_LHU,
            INSTR_LR_W, INSTR_AMOSWAP_W, INSTR_AMOADD_W,
            INSTR_AMOAND_W, INSTR_AMOOR_W, INSTR_AMOXOR_W,
            INSTR_AMOMAX_W, INSTR_AMOMIN_W, INSTR_AMOMAXU_W,
            INSTR_AMOMINU_W: late_result = 1'b1;
            default: late_result = 1'b0;
        endcase
    endfunction
    function automatic [1:0] select_next(input [4:0] rs, input valid_rs);
        if (valid_rs && next_mem_valid && ex_rd != 0 &&
            ex_rd == rs && !late_result(ex_instr)) select_next = 2'b01;
        else if (valid_rs && next_wb_valid && mem_rd != 0 && mem_rd == rs)
            select_next = 2'b10;
        else select_next = 2'b00;
    endfunction
    // Deliberately update on HOLD too: MEM/WB keep advancing during DIV.
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            forward_a_q <= 0;
            forward_b_q <= 0;
        end else begin
            forward_a_q <= select_next(next_rs1, next_v1);
            forward_b_q <= select_next(next_rs2, next_v2);
        end
    end
endmodule
