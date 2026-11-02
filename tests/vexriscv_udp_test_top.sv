`timescale 1ns/1ps
`default_nettype none
// Real production CPU and packet peripheral. WITH_MAC additionally connects
// two generated LiteEth nodes over GMII; the external UDP stream is then the
// simulated host node, and its IP metadata names the board destination.
module vexriscv_udp_test_top #(
    parameter BOOT_HEX="", parameter DIRECT_TPU=0, parameter ENABLE_CORDIC=1,
    parameter WITH_MAC=0
)(
    input wire clk,input wire eth_clk,input wire rst,
    input wire rx_valid,output wire rx_ready,input wire [31:0] rx_data,
    input wire rx_last,input wire [3:0] rx_last_be,input wire [3:0] rx_error,
    input wire [15:0] rx_src_port,input wire [15:0] rx_dst_port,
    input wire [31:0] rx_ip_address,input wire [15:0] rx_length,
    output wire tx_valid,input wire tx_ready,output wire [31:0] tx_data,
    output wire tx_last,output wire [3:0] tx_last_be,output wire [3:0] tx_error,
    output wire [15:0] tx_src_port,output wire [15:0] tx_dst_port,
    output wire [31:0] tx_ip_address,output wire [15:0] tx_length,
    output wire fault,output wire exit_valid,output wire [31:0] exit_code,
    output wire board_gmii_tx_en,output wire host_gmii_tx_en,
    output wire [31:0] board_crc_errors,output wire [31:0] host_crc_errors,
    output wire [31:0] board_preamble_errors,output wire [31:0] host_preamble_errors
);
    wire req_valid,req_ready,req_write,resp_valid,resp_ready,resp_error;
    wire [31:0] req_addr,req_wdata,resp_rdata;
    wire [3:0] req_wstrb;
    wire board_rx_valid,board_rx_ready,board_rx_last,board_tx_valid,board_tx_ready,board_tx_last;
    wire [31:0] board_rx_data,board_tx_data,board_rx_ip_address,board_tx_ip_address;
    wire [3:0] board_rx_last_be,board_tx_last_be,board_rx_error,board_tx_error;
    wire [15:0] board_rx_src_port,board_rx_dst_port,board_rx_length;
    wire [15:0] board_tx_src_port,board_tx_dst_port,board_tx_length;
    vexriscv_tpu_soc #(.BOOT_HEX(BOOT_HEX),.DIRECT_TPU(DIRECT_TPU),
        .ENABLE_CORDIC(ENABLE_CORDIC),.ENABLE_ETHERNET(1)) soc(
        .clk(clk),.rst(rst),.ready_to_run(!rst),.uart_rx(1'b1),.uart_tx(),
        .fault(fault),.pc_debug(),.ext_req_valid(req_valid),.ext_req_ready(req_ready),
        .ext_req_write(req_write),.ext_req_addr(req_addr),.ext_req_wdata(req_wdata),
        .ext_req_wstrb(req_wstrb),.ext_resp_valid(resp_valid),.ext_resp_ready(resp_ready),
        .ext_resp_rdata(resp_rdata),.ext_resp_error(resp_error),.report_valid(),.report_data(),
        .exit_valid(exit_valid),.exit_code(exit_code));
    tiny3tpu_udp_peripheral packets(
        .clk(clk),.rst(rst),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.req_wstrb(req_wstrb),
        .resp_valid(resp_valid),.resp_ready(resp_ready),.resp_rdata(resp_rdata),.resp_error(resp_error),
        .rx_valid(board_rx_valid),.rx_ready(board_rx_ready),.rx_data(board_rx_data),.rx_last(board_rx_last),
        .rx_last_be(board_rx_last_be),.rx_error(board_rx_error),.rx_src_port(board_rx_src_port),
        .rx_dst_port(board_rx_dst_port),.rx_ip_address(board_rx_ip_address),.rx_length(board_rx_length),
        .tx_valid(board_tx_valid),.tx_ready(board_tx_ready),.tx_data(board_tx_data),.tx_last(board_tx_last),
        .tx_last_be(board_tx_last_be),.tx_error(board_tx_error),.tx_src_port(board_tx_src_port),
        .tx_dst_port(board_tx_dst_port),.tx_ip_address(board_tx_ip_address),.tx_length(board_tx_length),
        .rx_pending(),.tx_busy(),.rx_drop_count(),.rx_bad_count());
    generate if(WITH_MAC)begin: full_mac
        wire [7:0] board_gmii_data,host_gmii_data;
        wire board_gmii_er,host_gmii_er,board_gtx_clk,host_gtx_clk;
        kc705_liteeth_udp board_network (
            .sys_clk(clk),.sys_rst(rst),.eth_tx_clk(eth_clk),.gmii_rx_clk(host_gtx_clk),
            .local_mac_address(48'h020000007051),.local_ip_address(32'hc0a80132),
            .gmii_rx_data(host_gmii_data),.gmii_rx_dv(host_gmii_tx_en),.gmii_rx_er(host_gmii_er),
            .gmii_gtx_clk(board_gtx_clk),.gmii_tx_data(board_gmii_data),
            .gmii_tx_en(board_gmii_tx_en),.gmii_tx_er(board_gmii_er),
            .rx_valid(board_rx_valid),.rx_ready(board_rx_ready),.rx_data(board_rx_data),.rx_last(board_rx_last),
            .rx_last_be(board_rx_last_be),.rx_error(board_rx_error),.rx_src_port(board_rx_src_port),
            .rx_dst_port(board_rx_dst_port),.rx_ip_address(board_rx_ip_address),.rx_length(board_rx_length),
            .tx_valid(board_tx_valid),.tx_ready(board_tx_ready),.tx_data(board_tx_data),.tx_last(board_tx_last),
            .tx_last_be(board_tx_last_be),.tx_error(board_tx_error),.tx_src_port(board_tx_src_port),
            .tx_dst_port(board_tx_dst_port),.tx_ip_address(board_tx_ip_address),.tx_length(board_tx_length),
            .crc_errors(board_crc_errors),.preamble_errors(board_preamble_errors));
        kc705_liteeth_udp host_network (
            .sys_clk(clk),.sys_rst(rst),.eth_tx_clk(eth_clk),.gmii_rx_clk(board_gtx_clk),
            .local_mac_address(48'h020000007052),.local_ip_address(32'hc0a80164),
            .gmii_rx_data(board_gmii_data),.gmii_rx_dv(board_gmii_tx_en),.gmii_rx_er(board_gmii_er),
            .gmii_gtx_clk(host_gtx_clk),.gmii_tx_data(host_gmii_data),
            .gmii_tx_en(host_gmii_tx_en),.gmii_tx_er(host_gmii_er),
            .tx_valid(rx_valid),.tx_ready(rx_ready),.tx_data(rx_data),.tx_last(rx_last),
            .tx_last_be(rx_last_be),.tx_error(rx_error),.tx_src_port(rx_src_port),
            .tx_dst_port(rx_dst_port),.tx_ip_address(rx_ip_address),.tx_length(rx_length),
            .rx_valid(tx_valid),.rx_ready(tx_ready),.rx_data(tx_data),.rx_last(tx_last),
            .rx_last_be(tx_last_be),.rx_error(tx_error),.rx_src_port(tx_src_port),
            .rx_dst_port(tx_dst_port),.rx_ip_address(tx_ip_address),.rx_length(tx_length),
            .crc_errors(host_crc_errors),.preamble_errors(host_preamble_errors));
    end else begin: stream_boundary
        assign board_rx_valid=rx_valid,rx_ready=board_rx_ready,board_rx_data=rx_data,board_rx_last=rx_last;
        assign board_rx_last_be=rx_last_be,board_rx_error=rx_error,board_rx_src_port=rx_src_port;
        assign board_rx_dst_port=rx_dst_port,board_rx_ip_address=rx_ip_address,board_rx_length=rx_length;
        assign tx_valid=board_tx_valid,board_tx_ready=tx_ready,tx_data=board_tx_data,tx_last=board_tx_last;
        assign tx_last_be=board_tx_last_be,tx_error=board_tx_error,tx_src_port=board_tx_src_port;
        assign tx_dst_port=board_tx_dst_port,tx_ip_address=board_tx_ip_address,tx_length=board_tx_length;
        assign board_gmii_tx_en=0,host_gmii_tx_en=0;
        assign board_crc_errors=0,host_crc_errors=0,board_preamble_errors=0,host_preamble_errors=0;
    end endgenerate
endmodule
`default_nettype wire
