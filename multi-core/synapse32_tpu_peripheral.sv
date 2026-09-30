`timescale 1ns/1ps
`default_nettype none
// Local fixed-latency peripheral port. Board logic must decode a non-overlapping
// MMIO region, gate enables, and mux cpu_rdata into Synapse32's load-data path.
// Address is a LOCAL byte offset. One shared clock/reset; not a CDC bridge.
module synapse32_tpu_peripheral (
    input wire clk, input wire rst_n,
    input wire cpu_wr_en, input wire cpu_rd_en,
    input wire [4:0] cpu_addr, input wire [31:0] cpu_wdata,
    input wire [3:0] cpu_wstrb, output wire [31:0] cpu_rdata
);
    wire [31:0] req_tdata;
    wire [3:0] req_tkeep;
    wire req_tlast;
    wire req_tvalid;
    wire req_tready;
    wire [31:0] resp_tdata;
    wire [3:0] resp_tkeep;
    wire resp_tlast;
    wire resp_tvalid;
    wire resp_tready;
    synapse32_axis_mailbox mailbox (
        .clk(clk), .rst_n(rst_n),
        .cpu_wr_en(cpu_wr_en),
        .cpu_rd_en(cpu_rd_en),
        .cpu_addr(cpu_addr),
        .cpu_wdata(cpu_wdata),
        .cpu_wstrb(cpu_wstrb),
        .cpu_rdata(cpu_rdata),
        .m_axis_tdata(req_tdata),
        .m_axis_tkeep(req_tkeep),
        .m_axis_tlast(req_tlast),
        .m_axis_tvalid(req_tvalid),
        .m_axis_tready(req_tready),
        .s_axis_tdata(resp_tdata),
        .s_axis_tkeep(resp_tkeep),
        .s_axis_tlast(resp_tlast),
        .s_axis_tvalid(resp_tvalid),
        .s_axis_tready(resp_tready)
    );
    tiny3tpu_axis transport (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(req_tdata),
        .s_axis_tkeep(req_tkeep),
        .s_axis_tlast(req_tlast),
        .s_axis_tvalid(req_tvalid),
        .s_axis_tready(req_tready),
        .m_axis_tdata(resp_tdata),
        .m_axis_tkeep(resp_tkeep),
        .m_axis_tlast(resp_tlast),
        .m_axis_tvalid(resp_tvalid),
        .m_axis_tready(resp_tready)
    );
endmodule
`default_nettype wire
