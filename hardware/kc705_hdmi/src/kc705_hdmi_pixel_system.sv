`default_nettype none
// Compiled program on RV32 -> compiler-selected dual TPU -> CPU pixels -> HDMI.
module kc705_hdmi_pixel_system #(parameter BOOT_HEX="", BOOT_WORDS=65536,
    FRAME_WIDTH=160, FRAME_HEIGHT=120, VIDEO_720P=0)(
    input wire clk,reset,enable,test_pattern,
    output wire [15:0] hdmi_d,
    output wire de,hsync,vsync,frame_tick,display_valid,display_bank,pending,
    output wire [31:0] frames,display_tag,
    output wire fault,exit_valid,report_valid,
    output wire [31:0] exit_code,report_data
);
    wire req_valid,req_ready,req_write,resp_valid,resp_ready,resp_error;
    wire [31:0] req_addr,req_wdata,resp_rdata;
    wire [3:0] req_wstrb;
    vexriscv_tpu_soc #(.BOOT_HEX(BOOT_HEX),.BOOT_WORDS(BOOT_WORDS),.DIRECT_TPU(1)) soc(
        .clk(clk),.rst(reset),.ready_to_run(!reset),.uart_rx(1'b1),.uart_tx(),
        .fault(fault),.pc_debug(),.ext_req_valid(req_valid),.ext_req_ready(req_ready),
        .ext_req_write(req_write),.ext_req_addr(req_addr),.ext_req_wdata(req_wdata),.ext_req_wstrb(req_wstrb),
        .ext_resp_valid(resp_valid),.ext_resp_ready(resp_ready),.ext_resp_rdata(resp_rdata),.ext_resp_error(resp_error),
        .report_valid(report_valid),.report_data(report_data),.exit_valid(exit_valid),.exit_code(exit_code));
    kc705_hdmi_pixels #(.WIDTH(FRAME_WIDTH),.HEIGHT(FRAME_HEIGHT),.VIDEO_720P(VIDEO_720P)) display(
        .clk(clk),.reset(reset),.enable(enable),.test_pattern(test_pattern),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.req_wstrb(req_wstrb),.resp_valid(resp_valid),.resp_ready(resp_ready),
        .resp_rdata(resp_rdata),.resp_error(resp_error),.hdmi_d(hdmi_d),.de(de),.hsync(hsync),.vsync(vsync),
        .frame_tick(frame_tick),.display_valid(display_valid),.display_bank(display_bank),.pending(pending),
        .frames(frames),.display_tag(display_tag));
endmodule
`default_nettype wire
