`timescale 1ns/1ps
`default_nettype none
// Native Synapse32 memory-port adapter, with full-address decode. Addresses
// must be physical (or bare-metal M-mode addresses). Reserve 0x20001000..1f.
// Hits remain asserted on faults so the board can exclude this region from RAM;
// side effects and data reads are independently gated by the fault inputs.
// Software contract: aligned LW/SW only, no atomics, one CPU owner.
module synapse32_tpu_mmio (
    input wire clk, input wire rst_n,
    input wire cpu_wr_en, input wire cpu_rd_en,
    input wire [31:0] cpu_wr_addr, input wire [31:0] cpu_rd_addr,
    input wire [31:0] cpu_wdata, input wire [3:0] cpu_wstrb,
    input wire [2:0] cpu_load_type,
    input wire cpu_store_fault, input wire cpu_load_fault,
    output wire write_hit, output wire read_hit,
    output wire [31:0] cpu_rdata
);
    assign write_hit = cpu_wr_addr[31:5] == (32'h20001000 >> 5);
    assign read_hit = cpu_rd_addr[31:5] == (32'h20001000 >> 5);
    wire [31:0] local_rdata;
    wire read_allowed = read_hit && !cpu_load_fault && cpu_load_type==3'b010;
    assign cpu_rdata = read_allowed ? local_rdata : 32'b0;
    synapse32_tpu_peripheral peripheral (
        .clk(clk), .rst_n(rst_n),
        .cpu_wr_en(cpu_wr_en && write_hit && !cpu_store_fault),
        .cpu_rd_en(cpu_rd_en && read_allowed),
        .cpu_addr(cpu_wr_en && write_hit ? cpu_wr_addr[4:0] : cpu_rd_addr[4:0]),
        .cpu_wdata(cpu_wdata), .cpu_wstrb(cpu_wstrb), .cpu_rdata(local_rdata)
    );
endmodule
`default_nettype wire
