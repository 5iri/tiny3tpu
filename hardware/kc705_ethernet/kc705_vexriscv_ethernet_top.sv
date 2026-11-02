`timescale 1ns/1ps
`default_nettype none
// KC705 VexRiscv/TPU at 100 MHz and hardware GMII ARP/IPv4/UDP at 1 Gb/s.
module kc705_vexriscv_ethernet_top #(
    parameter [31:0] LOCAL_IP = 32'hc0a80132,
    parameter [47:0] LOCAL_MAC = 48'h020000007051,
    parameter ENABLE_CORDIC = 0,
    parameter DIRECT_TPU = 0,
    parameter BOOT_WORDS = 16384,
`ifdef VEXRISCV_BOOT_HEX
    parameter BOOT_HEX=`VEXRISCV_BOOT_HEX
`else
    parameter BOOT_HEX=""
`endif
) (
    input wire clk_p, input wire clk_n, input wire reset_btn,
    input wire uart_rx, output wire uart_tx, output wire [7:0] led,
    input wire gmii_rx_clk, input wire [7:0] gmii_rx_data,
    input wire gmii_rx_dv, input wire gmii_rx_er,
    output wire gmii_gtx_clk, output wire [7:0] gmii_tx_data,
    output wire gmii_tx_en, output wire gmii_tx_er,
    output wire phy_rst_n, output wire phy_mdc, inout wire phy_mdio
);
    wire clk200;
    IBUFDS #(.IOSTANDARD("LVDS")) oscillator (.I(clk_p), .IB(clk_n), .O(clk200));
    wire clk_sys_unbuf, clk_sys, clk_eth_unbuf, clk_eth, pll_fb, locked;
    PLLE2_ADV #(
        .BANDWIDTH("OPTIMIZED"),
        .CLKFBOUT_MULT(5), // VCO = 200 MHz * 5 = 1000 MHz.
        .CLKFBOUT_PHASE(0.0),
        .CLKIN1_PERIOD(5.0),
        .CLKOUT0_DIVIDE(10),
        .CLKOUT1_DIVIDE(8), // 125 MHz independent GMII transmit clock. // 1000 MHz / 10 = 100 MHz system clock.
        .CLKOUT0_DUTY_CYCLE(0.5),
        .CLKOUT0_PHASE(0.0),
        .DIVCLK_DIVIDE(1),
        .REF_JITTER1(0.01)
    ) sys_pll (
        .CLKIN1(clk200), .CLKIN2(1'b0), .CLKINSEL(1'b1),
        .CLKFBIN(pll_fb), .CLKFBOUT(pll_fb),
        .CLKOUT0(clk_sys_unbuf), .CLKOUT1(clk_eth_unbuf),
        .LOCKED(locked),
        .PWRDWN(1'b0), .RST(1'b0),
        .DADDR(7'b0), .DCLK(1'b0), .DEN(1'b0), .DI(16'b0), .DWE(1'b0)
    );
    BUFG sys_bufg (.I(clk_sys_unbuf), .O(clk_sys));
    BUFG eth_bufg (.I(clk_eth_unbuf), .O(clk_eth));
    // Async assert, synchronized release.
    wire rst_async = reset_btn || !locked;
    reg [1:0] rst_sync = 2'b11;
    always @(posedge clk_sys or posedge rst_async)
        if(rst_async) rst_sync<=2'b11;
        else rst_sync<={rst_sync[0],1'b0};
    wire rst = rst_sync[1];
    wire req_valid, req_ready, soc_resp_ready, resp_valid, resp_error;
    wire req_write;
    wire [31:0] req_addr, req_wdata, resp_rdata;
    wire [3:0] req_wstrb;
    wire rx_valid,rx_ready,rx_last,tx_valid,tx_ready,tx_last;
    wire [31:0] rx_data,tx_data,rx_ip_address,tx_ip_address;
    wire [3:0] rx_last_be,tx_last_be,rx_error,tx_error;
    wire [15:0] rx_src_port,rx_dst_port,rx_length,tx_src_port,tx_dst_port,tx_length;
    wire rx_pending,tx_busy;
    wire [31:0] rx_drop_count,rx_bad_count,crc_errors,preamble_errors;
    wire phy_configured,phy_link_up,phy_mdio_fault;
    wire [15:0] phy_status;
    kc705_phy_mdio phy_management (.clk(clk_sys),.rst(rst),.phy_rst_n(phy_rst_n),
        .mdc(phy_mdc),.mdio(phy_mdio),.configured(phy_configured),.link_up(phy_link_up),
        .mdio_fault(phy_mdio_fault),.basic_status(phy_status));
    tiny3tpu_udp_peripheral packet_buffers (
        .clk(clk_sys),.rst(rst),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.req_wstrb(req_wstrb),
        .resp_valid(resp_valid),.resp_ready(soc_resp_ready),.resp_rdata(resp_rdata),.resp_error(resp_error),
        .rx_valid(rx_valid),.rx_ready(rx_ready),.rx_data(rx_data),.rx_last(rx_last),
        .rx_last_be(rx_last_be),.rx_error(rx_error),.rx_src_port(rx_src_port),.rx_dst_port(rx_dst_port),
        .rx_ip_address(rx_ip_address),.rx_length(rx_length),
        .tx_valid(tx_valid),.tx_ready(tx_ready),.tx_data(tx_data),.tx_last(tx_last),
        .tx_last_be(tx_last_be),.tx_error(tx_error),.tx_src_port(tx_src_port),.tx_dst_port(tx_dst_port),
        .tx_ip_address(tx_ip_address),.tx_length(tx_length),
        .rx_pending(rx_pending),.tx_busy(tx_busy),.rx_drop_count(rx_drop_count),.rx_bad_count(rx_bad_count));
    kc705_liteeth_udp ethernet (
        .sys_clk(clk_sys),.sys_rst(rst),.eth_tx_clk(clk_eth),
        .local_mac_address(LOCAL_MAC),.local_ip_address(LOCAL_IP),
        .gmii_rx_clk(gmii_rx_clk),.gmii_rx_data(gmii_rx_data),.gmii_rx_dv(gmii_rx_dv),.gmii_rx_er(gmii_rx_er),
        .gmii_gtx_clk(gmii_gtx_clk),.gmii_tx_data(gmii_tx_data),.gmii_tx_en(gmii_tx_en),.gmii_tx_er(gmii_tx_er),
        .rx_valid(rx_valid),.rx_ready(rx_ready),.rx_data(rx_data),.rx_last(rx_last),
        .rx_last_be(rx_last_be),.rx_error(rx_error),.rx_src_port(rx_src_port),.rx_dst_port(rx_dst_port),
        .rx_ip_address(rx_ip_address),.rx_length(rx_length),
        .tx_valid(tx_valid),.tx_ready(tx_ready),.tx_data(tx_data),.tx_last(tx_last),
        .tx_last_be(tx_last_be),.tx_error(tx_error),.tx_src_port(tx_src_port),.tx_dst_port(tx_dst_port),
        .tx_ip_address(tx_ip_address),.tx_length(tx_length),
        .crc_errors(crc_errors),.preamble_errors(preamble_errors));
    wire fault, exit_valid;
    wire [31:0] exit_code;
    vexriscv_tpu_soc #(.BOOT_HEX(BOOT_HEX), .BOOT_WORDS(BOOT_WORDS), .ENABLE_CORDIC(ENABLE_CORDIC),
                     .DIRECT_TPU(DIRECT_TPU),.ENABLE_ETHERNET(1)) soc (
        .clk(clk_sys), .rst(rst), .ready_to_run(locked && !rst),
        .uart_rx(uart_rx), .uart_tx(uart_tx), .fault(fault), .pc_debug(),
        .ext_req_valid(req_valid), .ext_req_ready(req_ready),
        .ext_req_write(req_write), .ext_req_addr(req_addr),
        .ext_req_wdata(req_wdata), .ext_req_wstrb(req_wstrb),
        .ext_resp_valid(resp_valid), .ext_resp_ready(soc_resp_ready),
        .ext_resp_rdata(resp_rdata), .ext_resp_error(resp_error),
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
    // LED: PLL lock, PHY configured, link, CPU fault, RX pending, TX busy, MDIO fault, heartbeat.
    assign led = {heartbeat[26],phy_mdio_fault,tx_busy,rx_pending,fault,phy_link_up,phy_configured,locked};
endmodule
`default_nettype wire
