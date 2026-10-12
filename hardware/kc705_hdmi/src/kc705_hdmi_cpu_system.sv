`default_nettype none
`include "mesh_config.vh"
// CPU, two 4x4 TPU cores, MMIO rasterizer, and HDMI scanout share 25.2 MHz.
// The CPU can calculate the next frame while the rasterizer draws this one.
module kc705_hdmi_cpu_system #(parameter BOOT_HEX="")(
    input wire clk,reset,enable,test_pattern,
    input wire [7:0] held,pressed,
    output wire [15:0] hdmi_d,frames,
    output wire de,hsync,vsync,frame_tick,render_busy,display_valid,display_bank,
    output wire [31:0] render_cycles,
    output wire [7:0] display_phase,
    output wire fault,exit_valid,report_valid,
    output wire [31:0] exit_code,report_data,
    output reg cpu_error
);
    wire req_valid,req_ready,req_write,resp_valid,resp_ready,resp_error;
    wire [31:0] req_addr,req_wdata,resp_rdata;
    wire [3:0] req_wstrb;
    wire command_ready,command_start,vertex_write;
    wire [7:0] command_phase;
    wire [11:0] vertex_index;
    wire [27:0] vertex_data;
    vexriscv_tpu_soc #(.BOOT_HEX(BOOT_HEX),.BOOT_WORDS(`HDMI_BOOT_WORDS),.DIRECT_TPU(1)) soc(
        .clk(clk),.rst(reset),.ready_to_run(!reset),.uart_rx(1'b1),.uart_tx(),
        .fault(fault),.pc_debug(),.ext_req_valid(req_valid),.ext_req_ready(req_ready),
        .ext_req_write(req_write),.ext_req_addr(req_addr),.ext_req_wdata(req_wdata),.ext_req_wstrb(req_wstrb),
        .ext_resp_valid(resp_valid),.ext_resp_ready(resp_ready),.ext_resp_rdata(resp_rdata),.ext_resp_error(resp_error),
        .report_valid(report_valid),.report_data(report_data),.exit_valid(exit_valid),.exit_code(exit_code));
    kc705_hdmi_mmio mmio(
        .clk(clk),.reset(reset),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.req_wstrb(req_wstrb),
        .resp_valid(resp_valid),.resp_ready(resp_ready),.resp_rdata(resp_rdata),.resp_error(resp_error),
        .command_ready(command_ready),.render_busy(render_busy),.display_valid(display_valid),
        .held(held),.pressed(pressed),.display_phase(display_phase),.render_cycles(render_cycles),.frames(frames),
        .command_start(command_start),.command_phase(command_phase),
        .vertex_write(vertex_write),.vertex_index(vertex_index),.vertex_data(vertex_data));
    kc705_hdmi_display #(.CPU_DRIVEN(1)) video(
        .clk(clk),.reset(reset),.enable(enable),.held(held),.pressed(pressed),.test_pattern(test_pattern),
        .command_start(command_start),.command_phase(command_phase),.command_ready(command_ready),
        .vertex_write(vertex_write),.vertex_index(vertex_index),.vertex_data(vertex_data),
        .hdmi_d(hdmi_d),.de(de),.hsync(hsync),.vsync(vsync),.frame_tick(frame_tick),
        .render_busy(render_busy),.display_valid(display_valid),.display_bank(display_bank),
        .render_cycles(render_cycles),.frames(frames),.display_phase(display_phase));
    always @(posedge clk)begin
        if(reset)cpu_error<=0;
        else if(fault || (exit_valid && exit_code!=0))cpu_error<=1;
    end
endmodule
`default_nettype wire
