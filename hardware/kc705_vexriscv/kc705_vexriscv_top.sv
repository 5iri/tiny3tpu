`timescale 1ns/1ps
`default_nettype none
module kc705_vexriscv_top #(
`ifdef VEXRISCV_BOOT_HEX
    parameter BOOT_HEX=`VEXRISCV_BOOT_HEX
`else
    parameter BOOT_HEX=""
`endif
) (
    input wire clk_p,input wire clk_n,input wire reset_btn,
    input wire uart_rx,output wire uart_tx,output wire [7:0] led,
    output wire [13:0] ddram_a,output wire [2:0] ddram_ba,
    output wire ddram_ras_n,ddram_cas_n,ddram_we_n,ddram_cs_n,
    output wire [7:0] ddram_dm,inout wire [63:0] ddram_dq,
    inout wire [7:0] ddram_dqs_p,ddram_dqs_n,
    output wire ddram_clk_p,ddram_clk_n,ddram_cke,ddram_odt,ddram_reset_n
);
    wire clk200,clk,rst,locked,init_done,init_error;
    wire dram_clk,dram_rst;
    IBUFDS #(.IOSTANDARD("LVDS")) oscillator (.I(clk_p),.IB(clk_n),.O(clk200));
    wire req_valid,req_ready,req_write,resp_valid,resp_ready,resp_error;
    wire [31:0] req_addr,req_wdata,resp_rdata;
    wire [3:0] req_wstrb;
    wire cpu_req_valid,cpu_req_ready,cpu_req_write,cpu_resp_valid,cpu_resp_ready,cpu_resp_error;
    wire [31:0] cpu_req_addr,cpu_req_wdata,cpu_resp_rdata;
    wire [3:0] cpu_req_wstrb;
`ifdef VEXRISCV_DDR_CDC
    req_resp_cdc clock_bridge (
        .s_clk(clk),.d_clk(dram_clk),.arst(reset_btn || !locked || rst || dram_rst),
        .s_req_valid(cpu_req_valid),.s_req_ready(cpu_req_ready),.s_req_write(cpu_req_write),
        .s_req_addr(cpu_req_addr),.s_req_wdata(cpu_req_wdata),.s_req_wstrb(cpu_req_wstrb),
        .s_resp_valid(cpu_resp_valid),.s_resp_ready(cpu_resp_ready),
        .s_resp_rdata(cpu_resp_rdata),.s_resp_error(cpu_resp_error),
        .d_req_valid(req_valid),.d_req_ready(req_ready),.d_req_write(req_write),
        .d_req_addr(req_addr),.d_req_wdata(req_wdata),.d_req_wstrb(req_wstrb),
        .d_resp_valid(resp_valid),.d_resp_ready(resp_ready),
        .d_resp_rdata(resp_rdata),.d_resp_error(resp_error)
    );
`else
    assign dram_clk=clk;
    assign dram_rst=rst;
    assign {req_valid,req_write,req_addr,req_wdata,req_wstrb} =
           {cpu_req_valid,cpu_req_write,cpu_req_addr,cpu_req_wdata,cpu_req_wstrb};
    assign {cpu_req_ready,cpu_resp_valid,cpu_resp_rdata,cpu_resp_error} =
           {req_ready,resp_valid,resp_rdata,resp_error};
    assign resp_ready=cpu_resp_ready;
`endif
    wire [29:0] wb_adr;
    wire [31:0] wb_dat_w,wb_dat_r;
    wire [3:0] wb_sel;
    wire wb_cyc,wb_stb,wb_we,wb_ack,wb_err;
    wire ctrl_select=wb_adr[29:14]==16'hf000;
    wire dram_select=wb_adr[29:28]==2'b01;
    wire ctrl_ack,ctrl_err,dram_ack,dram_err;
    wire [31:0] ctrl_data,dram_data;
    wire [23:0] burst_adr;
    wire [511:0] burst_dat_w,burst_dat_r;
    wire [63:0] burst_sel;
    wire burst_cyc,burst_stb,burst_we,burst_ack,burst_err;
    assign wb_ack=ctrl_select?ctrl_ack:dram_select?dram_ack:1'b0;
    assign wb_err=(!ctrl_select && !dram_select) || (ctrl_select?ctrl_err:dram_err);
    assign wb_dat_r=ctrl_select?ctrl_data:dram_data;
    litedram_wishbone_bridge bridge (
        .clk(dram_clk),.rst(dram_rst),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),
        .req_wstrb(req_write?req_wstrb:4'hf),
        .resp_valid(resp_valid),.resp_ready(resp_ready),.resp_rdata(resp_rdata),.resp_error(resp_error),
        .wb_adr(wb_adr),.wb_dat_w(wb_dat_w),.wb_dat_r(wb_dat_r),.wb_sel(wb_sel),
        .wb_cyc(wb_cyc),.wb_stb(wb_stb),.wb_we(wb_we),.wb_ack(wb_ack),.wb_err(wb_err)
    );
`ifdef VEXRISCV_DDR_PHY_ONLY
    assign {burst_adr,burst_dat_w,burst_sel,burst_cyc,burst_stb,burst_we} = 0;
    assign dram_data=0;
    assign dram_ack=0;
    assign dram_err=wb_cyc && dram_select;
`else
    litedram_wishbone32_to512 burst_bridge (
        .clk(dram_clk),.rst(dram_rst),.s_adr(wb_adr[27:0]),.s_dat_w(wb_dat_w),.s_dat_r(dram_data),
        .s_sel(wb_sel),.s_cyc(wb_cyc && dram_select),.s_stb(wb_stb && dram_select),
        .s_we(wb_we),.s_ack(dram_ack),.s_err(dram_err),
        .m_adr(burst_adr),.m_dat_w(burst_dat_w),.m_dat_r(burst_dat_r),.m_sel(burst_sel),
        .m_cyc(burst_cyc),.m_stb(burst_stb),.m_we(burst_we),.m_ack(burst_ack),.m_err(burst_err)
    );
`endif
    kc705_dram memory (
        .clk(clk200),.rst(reset_btn),
`ifdef VEXRISCV_DDR_CDC
        .user_clk(dram_clk),.user_rst(dram_rst),.user_cpu_clk(clk),.user_cpu_rst(rst),
`else
        .user_clk(clk),.user_rst(rst),
`endif
        .pll_locked(locked),.init_done(init_done),.init_error(init_error),
        .ddram_a(ddram_a),.ddram_ba(ddram_ba),.ddram_ras_n(ddram_ras_n),
        .ddram_cas_n(ddram_cas_n),.ddram_we_n(ddram_we_n),.ddram_cs_n(ddram_cs_n),
        .ddram_dm(ddram_dm),.ddram_dq(ddram_dq),.ddram_dqs_p(ddram_dqs_p),
        .ddram_dqs_n(ddram_dqs_n),.ddram_clk_p(ddram_clk_p),.ddram_clk_n(ddram_clk_n),
        .ddram_cke(ddram_cke),.ddram_odt(ddram_odt),.ddram_reset_n(ddram_reset_n),
        .user_port_cpu_adr(burst_adr),.user_port_cpu_dat_w(burst_dat_w),
        .user_port_cpu_dat_r(burst_dat_r),.user_port_cpu_sel(burst_sel),
        .user_port_cpu_cyc(burst_cyc),.user_port_cpu_stb(burst_stb),
        .user_port_cpu_we(burst_we),.user_port_cpu_ack(burst_ack),.user_port_cpu_err(burst_err),
        .wb_ctrl_adr({16'b0,wb_adr[13:0]}),.wb_ctrl_dat_w(wb_dat_w),.wb_ctrl_dat_r(ctrl_data),
        .wb_ctrl_sel(wb_sel),.wb_ctrl_cyc(wb_cyc && ctrl_select),.wb_ctrl_stb(wb_stb && ctrl_select),
        .wb_ctrl_we(wb_we),.wb_ctrl_ack(ctrl_ack),.wb_ctrl_err(ctrl_err),
        .wb_ctrl_cti(3'b0),.wb_ctrl_bte(2'b0)
    );
    wire fault,exit_valid;
    wire [31:0] exit_code;
    vexriscv_tpu_soc #(.BOOT_HEX(BOOT_HEX),.PIPELINED_DECODE(1)) soc (
        .clk(clk),.rst(rst),.ready_to_run(locked && !rst),
        .uart_rx(uart_rx),.uart_tx(uart_tx),.fault(fault),.pc_debug(),
        .ext_req_valid(cpu_req_valid),.ext_req_ready(cpu_req_ready),.ext_req_write(cpu_req_write),
        .ext_req_addr(cpu_req_addr),.ext_req_wdata(cpu_req_wdata),.ext_req_wstrb(cpu_req_wstrb),
        .ext_resp_valid(cpu_resp_valid),.ext_resp_ready(cpu_resp_ready),
        .ext_resp_rdata(cpu_resp_rdata),.ext_resp_error(cpu_resp_error),
        .report_valid(),.report_data(),.exit_valid(exit_valid),.exit_code(exit_code)
    );
    reg finished=0,passed=0;
    reg [26:0] heartbeat=0;
    always @(posedge clk) begin
        if(rst) begin finished<=0;passed<=0;heartbeat<=0; end
        else begin
            heartbeat<=heartbeat+1;
            if(exit_valid) begin finished<=1;passed<=exit_code==0; end
        end
    end
    assign led={heartbeat[26],1'b0,passed,finished,fault,init_error,init_done,locked};
endmodule
`default_nettype wire
