`timescale 1ns/1ps
// Real CPU, SoC, request/Wishbone bridge and production burst adapter.
// The host model replaces the 512-bit LiteDRAM port, not the CPU memory bus.
module vexriscv_ddr_wide_test_top #(parameter BOOT_HEX="", parameter ASYNC_DDR=0) (
    input wire clk,memory_clk,rst,ready_to_run,uart_rx,
    output wire uart_tx,fault,report_valid,exit_valid,
    output wire [31:0] pc_debug,report_data,exit_code,
    output wire [23:0] m_adr,
    output wire [511:0] m_dat_w,
    input wire [511:0] m_dat_r,
    output wire [63:0] m_sel,
    output wire m_cyc,m_stb,m_we,
    input wire m_ack,m_err
);
    wire req_valid,req_ready,req_write,resp_valid,resp_ready,resp_error;
    wire [31:0] req_addr,req_wdata,resp_rdata;
    wire [3:0] req_wstrb;
    wire mem_clk=ASYNC_DDR?memory_clk:clk;
    wire cpu_req_valid,cpu_req_ready,cpu_req_write,cpu_resp_valid,cpu_resp_ready,cpu_resp_error;
    wire [31:0] cpu_req_addr,cpu_req_wdata,cpu_resp_rdata;
    wire [3:0] cpu_req_wstrb;
    generate if(ASYNC_DDR) begin
        req_resp_cdc clock_bridge (
            .s_clk(clk),.d_clk(mem_clk),.arst(rst),
            .s_req_valid(cpu_req_valid),.s_req_ready(cpu_req_ready),.s_req_write(cpu_req_write),
            .s_req_addr(cpu_req_addr),.s_req_wdata(cpu_req_wdata),.s_req_wstrb(cpu_req_wstrb),
            .s_resp_valid(cpu_resp_valid),.s_resp_ready(cpu_resp_ready),
            .s_resp_rdata(cpu_resp_rdata),.s_resp_error(cpu_resp_error),
            .d_req_valid(req_valid),.d_req_ready(req_ready),.d_req_write(req_write),
            .d_req_addr(req_addr),.d_req_wdata(req_wdata),.d_req_wstrb(req_wstrb),
            .d_resp_valid(resp_valid),.d_resp_ready(resp_ready),
            .d_resp_rdata(resp_rdata),.d_resp_error(resp_error)
        );
    end else begin
        assign {req_valid,req_write,req_addr,req_wdata,req_wstrb} =
               {cpu_req_valid,cpu_req_write,cpu_req_addr,cpu_req_wdata,cpu_req_wstrb};
        assign {cpu_req_ready,cpu_resp_valid,cpu_resp_rdata,cpu_resp_error} =
               {req_ready,resp_valid,resp_rdata,resp_error};
        assign resp_ready=cpu_resp_ready;
    end endgenerate
    vexriscv_tpu_soc #(.BOOT_HEX(BOOT_HEX),.PIPELINED_DECODE(1)) soc (
        .clk(clk),.rst(rst),.ready_to_run(ready_to_run),.uart_rx(uart_rx),.uart_tx(uart_tx),
        .fault(fault),.pc_debug(pc_debug),.report_valid(report_valid),.report_data(report_data),
        .exit_valid(exit_valid),.exit_code(exit_code),
        .ext_req_valid(cpu_req_valid),.ext_req_ready(cpu_req_ready),.ext_req_write(cpu_req_write),
        .ext_req_addr(cpu_req_addr),.ext_req_wdata(cpu_req_wdata),.ext_req_wstrb(cpu_req_wstrb),
        .ext_resp_valid(cpu_resp_valid),.ext_resp_ready(cpu_resp_ready),.ext_resp_rdata(cpu_resp_rdata),.ext_resp_error(cpu_resp_error)
    );
    wire [29:0] wb_adr;
    wire [31:0] wb_dat_w,wb_dat_r;
    wire [3:0] wb_sel;
    wire wb_cyc,wb_stb,wb_we,wb_ack,wb_err,dram_err;
    wire dram_select=wb_adr[29:28]==2'b01;
    assign wb_err=!dram_select || dram_err;
    litedram_wishbone_bridge bridge (
        .clk(mem_clk),.rst(rst),.req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),
        .req_addr(req_addr),.req_wdata(req_wdata),.req_wstrb(req_write?req_wstrb:4'hf),
        .resp_valid(resp_valid),.resp_ready(resp_ready),.resp_rdata(resp_rdata),.resp_error(resp_error),
        .wb_adr(wb_adr),.wb_dat_w(wb_dat_w),.wb_dat_r(wb_dat_r),.wb_sel(wb_sel),
        .wb_cyc(wb_cyc),.wb_stb(wb_stb),.wb_we(wb_we),.wb_ack(wb_ack),.wb_err(wb_err)
    );
    litedram_wishbone32_to512 burst_bridge (
        .clk(mem_clk),.rst(rst),.s_adr(wb_adr[27:0]),.s_dat_w(wb_dat_w),.s_dat_r(wb_dat_r),
        .s_sel(wb_sel),.s_cyc(wb_cyc && dram_select),.s_stb(wb_stb && dram_select),
        .s_we(wb_we),.s_ack(wb_ack),.s_err(dram_err),
        .m_adr(m_adr),.m_dat_w(m_dat_w),.m_dat_r(m_dat_r),.m_sel(m_sel),
        .m_cyc(m_cyc),.m_stb(m_stb),.m_we(m_we),.m_ack(m_ack),.m_err(m_err)
    );
endmodule
