`default_nettype none
`include "instr_defines.vh"
module csr_exec (
    input wire [6:0] instr_id,
    input wire [31:0] rs1_value,
    input wire [4:0] rs1_addr,
    input wire [31:0] csr_read_data,
    output wire [31:0] csr_write_data,
    output wire csr_write_enable,
    output wire [31:0] rd_value
);
    wire rw_reg = instr_id == INSTR_CSRRW;
    wire rs_reg = instr_id == INSTR_CSRRS;
    wire rc_reg = instr_id == INSTR_CSRRC;
    wire rw_imm = instr_id == INSTR_CSRRWI;
    wire rs_imm = instr_id == INSTR_CSRRSI;
    wire rc_imm = instr_id == INSTR_CSRRCI;
    wire use_reg = rw_reg | rs_reg | rc_reg;
    wire use_imm = rw_imm | rs_imm | rc_imm;
    wire keep_old = rs_reg | rc_reg | rs_imm | rc_imm;
    wire clear_bits = rc_reg | rc_imm;
    wire [31:0] operand = ({32{use_reg}} & rs1_value) |
                         ({32{use_imm}} & {27'b0, rs1_addr});
    // Set/write share an OR plane; clear shares the old-data AND plane.
    assign csr_write_data = (csr_read_data & {32{keep_old}} &
                             ~(operand & {32{clear_bits}})) |
                            (operand & {32{!clear_bits}});
    assign csr_write_enable = rw_reg | rw_imm |
                              (keep_old & (|rs1_addr));
    assign rd_value = csr_read_data;
endmodule
