`timescale 1ns/1ps
`default_nettype none
// CPU-free KC705 trial. The upstream controller performs calibration and BIST.
module kc705_uberddr3_top #(
    parameter integer CONTROLLER_CLK_PERIOD = 10000,
    parameter integer DDR3_CLK_PERIOD = CONTROLLER_CLK_PERIOD / 4,
    parameter integer DIAGNOSTIC_WL = 0,
    parameter integer DIAGNOSTIC_UART = 0
) (
    input wire clk_p, clk_n, reset_btn,
    output wire [7:0] led,
    output wire [13:0] ddram_a, output wire [2:0] ddram_ba,
    output wire ddram_ras_n, ddram_cas_n, ddram_we_n, ddram_cs_n,
    output wire [7:0] ddram_dm, inout wire [63:0] ddram_dq,
    inout wire [7:0] ddram_dqs_p, ddram_dqs_n,
    output wire ddram_clk_p, ddram_clk_n, ddram_cke, ddram_odt, ddram_reset_n,
    output wire uart_tx
);
    wire clk200, feedback, feedback_buf, locked;
    wire controller_raw, ddr_raw, ref_raw, system_raw;
    wire controller_clk, ddr_clk, ref_clk, system_clk;
    IBUFDS #(.IOSTANDARD("LVDS")) oscillator (.I(clk_p), .IB(clk_n), .O(clk200));
    // 100 MHz mode: 800 MHz VCO -> 100 / 400 / 200 MHz.
    // 83.33 MHz mode: 1 GHz VCO -> 100 / 83.33 / 333.33 / 200 MHz.
    localparam integer PLL_MULT = CONTROLLER_CLK_PERIOD == 12000 ? 5 : 4;
    localparam integer PLL_CONTROLLER_DIV = CONTROLLER_CLK_PERIOD == 12000 ? 12 : 8;
    localparam integer PLL_DDR_DIV = CONTROLLER_CLK_PERIOD == 12000 ? 3 : 2;
    localparam integer PLL_REF_DIV = CONTROLLER_CLK_PERIOD == 12000 ? 5 : 4;
    localparam integer PLL_SYSTEM_DIV = CONTROLLER_CLK_PERIOD == 12000 ? 10 : 8;
    PLLE2_ADV #(.BANDWIDTH("OPTIMIZED"), .COMPENSATION("INTERNAL"),
        .DIVCLK_DIVIDE(1), .CLKFBOUT_MULT(PLL_MULT), .CLKIN1_PERIOD(5.0),
        .CLKOUT0_DIVIDE(PLL_CONTROLLER_DIV), .CLKOUT1_DIVIDE(PLL_DDR_DIV),
        .CLKOUT2_DIVIDE(PLL_REF_DIV), .CLKOUT3_DIVIDE(PLL_SYSTEM_DIV)) pll (
        .CLKIN1(clk200), .CLKIN2(1'b0), .CLKINSEL(1'b1),
        .CLKFBIN(feedback_buf), .CLKFBOUT(feedback),
        .CLKOUT0(controller_raw), .CLKOUT1(ddr_raw), .CLKOUT2(ref_raw),
        .CLKOUT3(system_raw), .CLKOUT4(), .CLKOUT5(), .LOCKED(locked),
        .RST(reset_btn), .PWRDWN(1'b0),
        .DADDR(7'b0), .DCLK(1'b0), .DEN(1'b0), .DI(16'b0), .DWE(1'b0), .DO(), .DRDY()
    );
    BUFG feedback_buffer (.I(feedback), .O(feedback_buf));
    BUFG controller_buffer (.I(controller_raw), .O(controller_clk));
    BUFG ddr_buffer (.I(ddr_raw), .O(ddr_clk));
    BUFG ref_buffer (.I(ref_raw), .O(ref_clk));
    BUFG system_buffer (.I(system_raw), .O(system_clk));
    (* ASYNC_REG = "TRUE" *) reg [3:0] reset_pipe = 0;
    wire async_reset = reset_btn || !locked;
    always @(posedge controller_clk or posedge async_reset)
        if (async_reset) reset_pipe <= 0;
        else reset_pipe <= {reset_pipe[2:0], 1'b1};

    wire done, passed, failed, raw_dq0;
    wire [31:0] debug;
    (* ASYNC_REG = "TRUE" *) reg [1:0] system_reset_pipe = 0;
    always @(posedge system_clk or posedge async_reset)
        if (async_reset) system_reset_pipe <= 0;
        else system_reset_pipe <= {system_reset_pipe[0], 1'b1};
    (* keep = "true" *) reg [26:0] system_heartbeat = 0;
    always @(posedge system_clk)
        if (!system_reset_pipe[1]) system_heartbeat <= 0;
        else system_heartbeat <= system_heartbeat + 1'b1;
    kc705_uberddr3_status status (.clk(controller_clk), .rst_n(reset_pipe[3]),
        .done(done), .debug(debug), .passed(passed), .failed(failed));
    // Normal: LED[6:3] calibration state, LED7 100 MHz heartbeat.
    // WL diagnostic: LED[6:3] feedback/lane while training; after timeout,
    // LED[7:3] show the live data ODELAY tap as a five-bit value. The controller
    // continues scanning after the status watchdog marks failure.
    wire [7:0] diagnostic_leds = failed && !debug[31]
        ? {debug[4:0], failed, passed, locked}
        : {system_heartbeat[26], debug[8:5], failed, passed, locked};
    assign led = DIAGNOSTIC_WL ? diagnostic_leds
                               : {system_heartbeat[26], debug[3:0], failed, passed, locked};
    generate if (DIAGNOSTIC_UART) begin : uart_diagnostic
        kc705_uberddr3_uart_diag #(.CLK_HZ(64'd1_000_000_000_000 / CONTROLLER_CLK_PERIOD)) monitor (
            .clk(controller_clk), .rst_n(reset_pipe[3]), .debug(debug),
            .done(done), .passed(passed), .failed(failed), .locked(locked),
            .raw_dq0(raw_dq0),
            .tx(uart_tx)
        );
    end else begin : no_uart_diagnostic
        assign uart_tx = 1'b1;
    end endgenerate

    ddr3_top #(
        .CONTROLLER_CLK_PERIOD(CONTROLLER_CLK_PERIOD), .DDR3_CLK_PERIOD(DDR3_CLK_PERIOD),
        .ROW_BITS(14), .COL_BITS(10), .BA_BITS(3), .BYTE_LANES(8),
        .AUX_WIDTH(4), .DUAL_RANK_DIMM(0), .SDRAM_CAPACITY(2),
        // Conservative timings for the KC705 MT8JTF12864 1 GiB module.
        .SPEED_BIN(0), .TRCD(15000), .TRP(15000), .TRAS(37500),
        .ODELAY_SUPPORTED(1), .MICRON_SIM(0), .SECOND_WISHBONE(0),
        .ECC_ENABLE(0), .DLL_OFF(0), .WB_ERROR(0),
        .BIST_MODE(1), .BIST_TEST_DATAMASK(1),
        .DIC(2'b01), .RTT_NOM(3'b001), .SELF_REFRESH(0)
    ) memory (
        .i_controller_clk(controller_clk), .i_ddr3_clk(ddr_clk),
        .i_ref_clk(ref_clk), .i_ddr3_clk_90(1'b0), .i_rst_n(reset_pipe[3]),
        .i_wb_cyc(1'b1), .i_wb_stb(1'b0), .i_wb_we(1'b0),
        .i_wb_addr(24'b0), .i_wb_data(512'b0), .i_wb_sel(64'hffffffffffffffff), .i_aux(4'b0),
        .o_wb_stall(), .o_wb_ack(), .o_wb_err(), .o_wb_data(), .o_aux(),
        .i_wb2_cyc(1'b0), .i_wb2_stb(1'b0), .i_wb2_we(1'b0),
        .i_wb2_addr(7'b0), .i_wb2_data(32'b0), .i_wb2_sel(4'b0),
        .o_wb2_stall(), .o_wb2_ack(), .o_wb2_data(),
        .o_ddr3_clk_p(ddram_clk_p), .o_ddr3_clk_n(ddram_clk_n),
        .o_ddr3_reset_n(ddram_reset_n), .o_ddr3_cke(ddram_cke), .o_ddr3_cs_n(ddram_cs_n),
        .o_ddr3_ras_n(ddram_ras_n), .o_ddr3_cas_n(ddram_cas_n), .o_ddr3_we_n(ddram_we_n),
        .o_ddr3_addr(ddram_a), .o_ddr3_ba_addr(ddram_ba),
        .io_ddr3_dq(ddram_dq), .io_ddr3_dqs(ddram_dqs_p), .io_ddr3_dqs_n(ddram_dqs_n),
        .o_ddr3_dm(ddram_dm), .o_ddr3_odt(ddram_odt),
        .o_calib_complete(done), .o_debug1(debug), .o_debug_raw_dq0(raw_dq0),
        .i_user_self_refresh(1'b0), .uart_tx()
    );
endmodule
`default_nettype wire
