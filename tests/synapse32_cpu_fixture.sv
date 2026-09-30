`timescale 1ns/1ps
`default_nettype none
// Simulation fixture, NOT a board top: memory is supplied by the C++ harness.
// Instantiate riscv_cpu directly so Synapse32's own module top is not compiled.
module synapse32_cpu_fixture (
    input wire clk, input wire rst_n,
    input wire [31:0] instr, input wire [31:0] ram_rdata,
    output wire [31:0] pc, output wire [31:0] rd_addr,
    output wire [31:0] wr_addr, output wire [31:0] wr_data,
    output wire [3:0] wr_strb, output wire rd_en, output wire wr_en
);
    wire [31:0] mailbox_data;
    wire [2:0] load_type;
    wire rd_select, wr_select;
    wire [31:0] read_data = rd_select ? mailbox_data : ram_rdata;
    synapse32_tpu_mmio peripheral (
        .clk(clk), .rst_n(rst_n), .cpu_wr_en(wr_en), .cpu_rd_en(rd_en),
        .cpu_wr_addr(wr_addr), .cpu_rd_addr(rd_addr),
        .cpu_wdata(wr_data), .cpu_wstrb(wr_strb), .cpu_load_type(load_type),
        .cpu_store_fault(1'b0), .cpu_load_fault(1'b0),
        .write_hit(wr_select), .read_hit(rd_select), .cpu_rdata(mailbox_data)
    );
    riscv_cpu cpu (
        .clk(clk), .rst(!rst_n), .module_instr_in(instr),
        .module_read_data_in(read_data), .module_pc_out(pc),
        .module_wr_data_out(wr_data), .module_mem_wr_en(wr_en),
        .module_mem_rd_en(rd_en), .module_read_addr(rd_addr),
        .module_write_addr(wr_addr), .module_write_byte_enable(wr_strb),
        .module_load_type(load_type), .module_load_page_fault_in(1'b0),
        .module_store_page_fault_in(1'b0), .module_page_fault_addr_in(32'b0),
        .module_instr_page_fault_in(1'b0), .module_data_mmu_enable_out(),
        .module_data_privilege_out(), .module_satp_out(),
        .module_data_sum_out(), .module_data_mxr_out(),
        .module_instr_mmu_enable_out(), .module_instr_privilege_out(),
        .timer_interrupt(1'b0), .software_interrupt(1'b0), .external_interrupt(1'b0)
    );
endmodule
`default_nettype wire
