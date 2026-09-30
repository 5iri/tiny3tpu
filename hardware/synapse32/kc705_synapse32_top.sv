`timescale 1ns/1ps
`default_nettype none
module kc705_synapse32_top #(
`ifdef SYNAPSE32_BOOT_HEX
    parameter BOOT_HEX=`SYNAPSE32_BOOT_HEX
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
    IBUFDS #(.IOSTANDARD("LVDS")) oscillator (.I(clk_p),.IB(clk_n),.O(clk200));
    wire req_valid,req_ready,req_write,resp_valid,resp_ready,resp_error;
    wire [31:0] req_addr,req_wdata,resp_rdata;
    wire [3:0] req_wstrb;
    wire [29:0] wb_adr;
    wire [31:0] wb_dat_w,wb_dat_r;
    wire [3:0] wb_sel;
    wire wb_cyc,wb_stb,wb_we,wb_ack,wb_err;
    wire ctrl_select=wb_adr[29:14]==16'hf000;
    wire dram_select=wb_adr[29:28]==2'b01;
    wire ctrl_ack,ctrl_err,dram_ack,dram_err;
    wire [31:0] ctrl_data,dram_data;
    assign wb_ack=ctrl_select?ctrl_ack:dram_select?dram_ack:1'b0;
    assign wb_err=(!ctrl_select && !dram_select) || (ctrl_select?ctrl_err:dram_err);
    assign wb_dat_r=ctrl_select?ctrl_data:dram_data;
    litedram_wishbone_bridge bridge (
        .clk(clk),.rst(rst),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),
        .req_wstrb(req_write?req_wstrb:4'hf),
        .resp_valid(resp_valid),.resp_ready(resp_ready),.resp_rdata(resp_rdata),.resp_error(resp_error),
        .wb_adr(wb_adr),.wb_dat_w(wb_dat_w),.wb_dat_r(wb_dat_r),.wb_sel(wb_sel),
        .wb_cyc(wb_cyc),.wb_stb(wb_stb),.wb_we(wb_we),.wb_ack(wb_ack),.wb_err(wb_err)
    );
    kc705_dram memory (
        .clk(clk200),.rst(reset_btn),.user_clk(clk),.user_rst(rst),
        .pll_locked(locked),.init_done(init_done),.init_error(init_error),
        .ddram_a(ddram_a),.ddram_ba(ddram_ba),.ddram_ras_n(ddram_ras_n),
        .ddram_cas_n(ddram_cas_n),.ddram_we_n(ddram_we_n),.ddram_cs_n(ddram_cs_n),
        .ddram_dm(ddram_dm),.ddram_dq(ddram_dq),.ddram_dqs_p(ddram_dqs_p),
        .ddram_dqs_n(ddram_dqs_n),.ddram_clk_p(ddram_clk_p),.ddram_clk_n(ddram_clk_n),
        .ddram_cke(ddram_cke),.ddram_odt(ddram_odt),.ddram_reset_n(ddram_reset_n),
        .user_port_cpu_adr(wb_adr[27:0]),.user_port_cpu_dat_w(wb_dat_w),
        .user_port_cpu_dat_r(dram_data),.user_port_cpu_sel(wb_sel),
        .user_port_cpu_cyc(wb_cyc && dram_select),.user_port_cpu_stb(wb_stb && dram_select),
        .user_port_cpu_we(wb_we),.user_port_cpu_ack(dram_ack),.user_port_cpu_err(dram_err),
        .wb_ctrl_adr({16'b0,wb_adr[13:0]}),.wb_ctrl_dat_w(wb_dat_w),.wb_ctrl_dat_r(ctrl_data),
        .wb_ctrl_sel(wb_sel),.wb_ctrl_cyc(wb_cyc && ctrl_select),.wb_ctrl_stb(wb_stb && ctrl_select),
        .wb_ctrl_we(wb_we),.wb_ctrl_ack(ctrl_ack),.wb_ctrl_err(ctrl_err),
        .wb_ctrl_cti(3'b0),.wb_ctrl_bte(2'b0)
    );
    wire fault,exit_valid;
    wire [31:0] exit_code;
    synapse32_dram_soc #(.BOOT_HEX(BOOT_HEX)) soc (
        .clk(clk),.rst(rst),.ready_to_run(locked && !rst),
        .uart_rx(uart_rx),.uart_tx(uart_tx),.fault(fault),.pc_debug(),
        .ext_req_valid(req_valid),.ext_req_ready(req_ready),.ext_req_write(req_write),
        .ext_req_addr(req_addr),.ext_req_wdata(req_wdata),.ext_req_wstrb(req_wstrb),
        .ext_resp_valid(resp_valid),.ext_resp_ready(resp_ready),
        .ext_resp_rdata(resp_rdata),.ext_resp_error(resp_error),
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
