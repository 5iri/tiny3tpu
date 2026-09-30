`timescale 1ns/1ps
`default_nettype none
// Only board clock/reset, DDR3 pins and status LEDs. No processor or firmware.
module kc705_ddr_only_top (
    input wire clk_p, clk_n, reset_btn,
    output wire [7:0] led,
    output wire [13:0] ddram_a, output wire [2:0] ddram_ba,
    output wire ddram_ras_n, ddram_cas_n, ddram_we_n, ddram_cs_n,
    output wire [7:0] ddram_dm, inout wire [63:0] ddram_dq,
    inout wire [7:0] ddram_dqs_p, ddram_dqs_n,
    output wire ddram_clk_p, ddram_clk_n, ddram_cke, ddram_odt, ddram_reset_n
);
    wire clk200, clk, rst, locked;
    IBUFDS #(.IOSTANDARD("LVDS")) oscillator (.I(clk_p), .IB(clk_n), .O(clk200));
    wire [29:0] ctrl_adr;
    wire [31:0] ctrl_dat_w, ctrl_dat_r;
    wire [3:0] ctrl_sel;
    wire ctrl_cyc, ctrl_stb, ctrl_we, ctrl_ack, ctrl_err;
    wire [23:0] mem_adr;
    wire [511:0] mem_dat_w, mem_dat_r;
    wire [63:0] mem_sel;
    wire mem_cyc, mem_stb, mem_we, mem_ack, mem_err;
    wire initialized, calibrated, passed, failed, busy;
    wire [2:0] failure_code;
    kc705_ddr_engine engine (
        .sys_clk(clk), .sys_rst(rst),
        .ctrl_adr(ctrl_adr), .ctrl_dat_w(ctrl_dat_w), .ctrl_dat_r(ctrl_dat_r),
        .ctrl_sel(ctrl_sel), .ctrl_cyc(ctrl_cyc), .ctrl_stb(ctrl_stb),
        .ctrl_we(ctrl_we), .ctrl_ack(ctrl_ack), .ctrl_err(ctrl_err),
        .mem_adr(mem_adr), .mem_dat_w(mem_dat_w), .mem_dat_r(mem_dat_r),
        .mem_sel(mem_sel), .mem_cyc(mem_cyc), .mem_stb(mem_stb),
        .mem_we(mem_we), .mem_ack(mem_ack), .mem_err(mem_err),
        .initialized(initialized), .calibrated(calibrated), .passed(passed),
        .failed(failed), .busy(busy), .failure_code(failure_code),
        .failure_address(), .failure_lanes(), .stage()
    );
    kc705_dram memory (
        .clk(clk200), .rst(reset_btn), .user_clk(clk), .user_rst(rst),
        .pll_locked(locked), .init_done(), .init_error(),
        .ddram_a(ddram_a), .ddram_ba(ddram_ba), .ddram_ras_n(ddram_ras_n),
        .ddram_cas_n(ddram_cas_n), .ddram_we_n(ddram_we_n), .ddram_cs_n(ddram_cs_n),
        .ddram_dm(ddram_dm), .ddram_dq(ddram_dq), .ddram_dqs_p(ddram_dqs_p),
        .ddram_dqs_n(ddram_dqs_n), .ddram_clk_p(ddram_clk_p), .ddram_clk_n(ddram_clk_n),
        .ddram_cke(ddram_cke), .ddram_odt(ddram_odt), .ddram_reset_n(ddram_reset_n),
        .user_port_test_adr(mem_adr), .user_port_test_dat_w(mem_dat_w),
        .user_port_test_dat_r(mem_dat_r), .user_port_test_sel(mem_sel),
        .user_port_test_cyc(mem_cyc), .user_port_test_stb(mem_stb),
        .user_port_test_we(mem_we), .user_port_test_ack(mem_ack), .user_port_test_err(mem_err),
        .wb_ctrl_adr(ctrl_adr), .wb_ctrl_dat_w(ctrl_dat_w), .wb_ctrl_dat_r(ctrl_dat_r),
        .wb_ctrl_sel(ctrl_sel), .wb_ctrl_cyc(ctrl_cyc), .wb_ctrl_stb(ctrl_stb),
        .wb_ctrl_we(ctrl_we), .wb_ctrl_ack(ctrl_ack), .wb_ctrl_err(ctrl_err),
        .wb_ctrl_cti(3'b0), .wb_ctrl_bte(2'b0)
    );
    reg [26:0] heartbeat=0;
    always @(posedge clk) begin
        if (rst) heartbeat<=0;
        else heartbeat<=heartbeat+1;
    end
    // A failure replaces the low three status LEDs with its numeric code.
    assign led = {heartbeat[26], busy, failed, passed, calibrated,
                  failed ? failure_code : {initialized, !rst, locked}};
endmodule
`default_nettype wire
