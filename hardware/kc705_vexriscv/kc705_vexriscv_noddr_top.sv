`timescale 1ns/1ps
`default_nettype none
// KC705 VexRiscv + TPU boot-RAM self-test at 100 MHz.
module kc705_vexriscv_noddr_top #(
`ifdef VEXRISCV_BOOT_HEX
    parameter BOOT_HEX=`VEXRISCV_BOOT_HEX
`else
    parameter BOOT_HEX=""
`endif
) (
    input wire clk_p, input wire clk_n, input wire reset_btn,
    input wire uart_rx, output wire uart_tx, output wire [7:0] led
);
    wire clk200;
    IBUFDS #(.IOSTANDARD("LVDS")) oscillator (.I(clk_p), .IB(clk_n), .O(clk200));
    wire clk_sys_unbuf, clk_sys, pll_fb, locked;
    PLLE2_ADV #(
        .BANDWIDTH("OPTIMIZED"),
        .CLKFBOUT_MULT(5), // VCO = 200 MHz * 5 = 1000 MHz.
        .CLKFBOUT_PHASE(0.0),
        .CLKIN1_PERIOD(5.0),
        .CLKOUT0_DIVIDE(10), // 1000 MHz / 10 = 100 MHz system clock.
        .CLKOUT0_DUTY_CYCLE(0.5),
        .CLKOUT0_PHASE(0.0),
        .DIVCLK_DIVIDE(1),
        .REF_JITTER1(0.01)
    ) sys_pll (
        .CLKIN1(clk200), .CLKIN2(1'b0), .CLKINSEL(1'b1),
        .CLKFBIN(pll_fb), .CLKFBOUT(pll_fb),
        .CLKOUT0(clk_sys_unbuf),
        .LOCKED(locked),
        .PWRDWN(1'b0), .RST(1'b0),
        .DADDR(7'b0), .DCLK(1'b0), .DEN(1'b0), .DI(16'b0), .DWE(1'b0)
    );
    BUFG sys_bufg (.I(clk_sys_unbuf), .O(clk_sys));
    // Async assert, synchronized release.
    wire rst_async = reset_btn || !locked;
    reg [1:0] rst_sync = 2'b11;
    always @(posedge clk_sys) rst_sync <= {rst_sync[0], rst_async};
    wire rst = rst_sync[1];
    // No DDR/CSR target exists: fail loudly so stray accesses raise fault.
    // The error response is held until the SoC acknowledges it.
    wire req_valid, soc_resp_ready;
    wire req_write;
    wire [31:0] req_addr, req_wdata;
    wire [3:0] req_wstrb;
    reg ext_qvalid = 1'b0;
    always @(posedge clk_sys) begin
        if (rst) ext_qvalid <= 1'b0;
        else if (soc_resp_ready) ext_qvalid <= 1'b0;
        else if (req_valid) ext_qvalid <= 1'b1;
    end
    wire fault, exit_valid;
    wire [31:0] exit_code;
    vexriscv_tpu_soc #(.BOOT_HEX(BOOT_HEX)) soc (
        .clk(clk_sys), .rst(rst), .ready_to_run(locked && !rst),
        .uart_rx(uart_rx), .uart_tx(uart_tx), .fault(fault), .pc_debug(),
        .ext_req_valid(req_valid), .ext_req_ready(1'b1),
        .ext_req_write(req_write), .ext_req_addr(req_addr),
        .ext_req_wdata(req_wdata), .ext_req_wstrb(req_wstrb),
        .ext_resp_valid(ext_qvalid), .ext_resp_ready(soc_resp_ready),
        .ext_resp_rdata(32'b0), .ext_resp_error(1'b1),
        .report_valid(), .report_data(), .exit_valid(exit_valid), .exit_code(exit_code)
    );
    reg finished = 1'b0, passed = 1'b0;
    reg [26:0] heartbeat = 27'b0;
    always @(posedge clk_sys) begin
        if (rst) begin finished <= 1'b0; passed <= 1'b0; heartbeat <= 27'b0; end
        else begin
            heartbeat <= heartbeat + 27'b1;
            if (exit_valid) begin finished <= 1'b1; passed <= exit_code == 32'b0; end
        end
    end
    // LED bit positions match the DDR bring-up top: 0 lock, 3 fault,
    // 4 finished, 5 passed, 7 heartbeat. Positions 1, 2, 6 are unused here.
    assign led = {heartbeat[26], 1'b0, passed, finished, fault, 2'b0, locked};
endmodule
`default_nettype wire
