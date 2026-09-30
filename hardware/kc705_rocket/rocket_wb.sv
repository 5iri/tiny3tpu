`timescale 1ns/1ps
`default_nettype none
// Pinned Rocket wrapper: cached memory and uncached MMIO stay separate.
module rocket_wb(input wire clk, rst,
 output wire m_cyc,m_stb,m_we, output wire [29:0] m_adr,
 output wire [31:0] m_dat_w,output wire [3:0] m_sel,
 input wire [31:0] m_dat_r,input wire m_ack,m_err,
 output wire u_cyc,u_stb,u_we, output wire [29:0] u_adr,
 output wire [31:0] u_dat_w,output wire [3:0] u_sel,
 input wire [31:0] u_dat_r,input wire u_ack,u_err);
 wire  mem_axi4_0_aw_ready;
 wire  mem_axi4_0_aw_valid;
 wire [3:0] mem_axi4_0_aw_bits_id;
 wire [31:0] mem_axi4_0_aw_bits_addr;
 wire [7:0] mem_axi4_0_aw_bits_len;
 wire [2:0] mem_axi4_0_aw_bits_size;
 wire [1:0] mem_axi4_0_aw_bits_burst;
 wire  mem_axi4_0_aw_bits_lock;
 wire [3:0] mem_axi4_0_aw_bits_cache;
 wire [2:0] mem_axi4_0_aw_bits_prot;
 wire [3:0] mem_axi4_0_aw_bits_qos;
 wire  mem_axi4_0_w_ready;
 wire  mem_axi4_0_w_valid;
 wire [63:0] mem_axi4_0_w_bits_data;
 wire [7:0] mem_axi4_0_w_bits_strb;
 wire  mem_axi4_0_w_bits_last;
 wire  mem_axi4_0_b_ready;
 wire  mem_axi4_0_b_valid;
 wire [3:0] mem_axi4_0_b_bits_id;
 wire [1:0] mem_axi4_0_b_bits_resp;
 wire  mem_axi4_0_ar_ready;
 wire  mem_axi4_0_ar_valid;
 wire [3:0] mem_axi4_0_ar_bits_id;
 wire [31:0] mem_axi4_0_ar_bits_addr;
 wire [7:0] mem_axi4_0_ar_bits_len;
 wire [2:0] mem_axi4_0_ar_bits_size;
 wire [1:0] mem_axi4_0_ar_bits_burst;
 wire  mem_axi4_0_ar_bits_lock;
 wire [3:0] mem_axi4_0_ar_bits_cache;
 wire [2:0] mem_axi4_0_ar_bits_prot;
 wire [3:0] mem_axi4_0_ar_bits_qos;
 wire  mem_axi4_0_r_ready;
 wire  mem_axi4_0_r_valid;
 wire [3:0] mem_axi4_0_r_bits_id;
 wire [63:0] mem_axi4_0_r_bits_data;
 wire [1:0] mem_axi4_0_r_bits_resp;
 wire  mem_axi4_0_r_bits_last;
 wire  mmio_axi4_0_aw_ready;
 wire  mmio_axi4_0_aw_valid;
 wire [3:0] mmio_axi4_0_aw_bits_id;
 wire [30:0] mmio_axi4_0_aw_bits_addr;
 wire [7:0] mmio_axi4_0_aw_bits_len;
 wire [2:0] mmio_axi4_0_aw_bits_size;
 wire [1:0] mmio_axi4_0_aw_bits_burst;
 wire  mmio_axi4_0_aw_bits_lock;
 wire [3:0] mmio_axi4_0_aw_bits_cache;
 wire [2:0] mmio_axi4_0_aw_bits_prot;
 wire [3:0] mmio_axi4_0_aw_bits_qos;
 wire  mmio_axi4_0_w_ready;
 wire  mmio_axi4_0_w_valid;
 wire [63:0] mmio_axi4_0_w_bits_data;
 wire [7:0] mmio_axi4_0_w_bits_strb;
 wire  mmio_axi4_0_w_bits_last;
 wire  mmio_axi4_0_b_ready;
 wire  mmio_axi4_0_b_valid;
 wire [3:0] mmio_axi4_0_b_bits_id;
 wire [1:0] mmio_axi4_0_b_bits_resp;
 wire  mmio_axi4_0_ar_ready;
 wire  mmio_axi4_0_ar_valid;
 wire [3:0] mmio_axi4_0_ar_bits_id;
 wire [30:0] mmio_axi4_0_ar_bits_addr;
 wire [7:0] mmio_axi4_0_ar_bits_len;
 wire [2:0] mmio_axi4_0_ar_bits_size;
 wire [1:0] mmio_axi4_0_ar_bits_burst;
 wire  mmio_axi4_0_ar_bits_lock;
 wire [3:0] mmio_axi4_0_ar_bits_cache;
 wire [2:0] mmio_axi4_0_ar_bits_prot;
 wire [3:0] mmio_axi4_0_ar_bits_qos;
 wire  mmio_axi4_0_r_ready;
 wire  mmio_axi4_0_r_valid;
 wire [3:0] mmio_axi4_0_r_bits_id;
 wire [63:0] mmio_axi4_0_r_bits_data;
 wire [1:0] mmio_axi4_0_r_bits_resp;
 wire  mmio_axi4_0_r_bits_last;
 ExampleRocketSystem cpu (
 .clock(clk),
 .reset(rst),
 .resetctrl_hartIsInReset_0(rst),
 .debug_clock(clk),
 .debug_reset(rst),
 .debug_clockeddmi_dmi_req_ready(),
 .debug_clockeddmi_dmi_req_valid('0),
 .debug_clockeddmi_dmi_req_bits_addr('0),
 .debug_clockeddmi_dmi_req_bits_data('0),
 .debug_clockeddmi_dmi_req_bits_op('0),
 .debug_clockeddmi_dmi_resp_ready('0),
 .debug_clockeddmi_dmi_resp_valid(),
 .debug_clockeddmi_dmi_resp_bits_data(),
 .debug_clockeddmi_dmi_resp_bits_resp(),
 .debug_clockeddmi_dmiClock(clk),
 .debug_clockeddmi_dmiReset(rst),
 .debug_ndreset(),
 .debug_dmactive(),
 .debug_dmactiveAck('0),
 .mem_axi4_0_aw_ready(mem_axi4_0_aw_ready),
 .mem_axi4_0_aw_valid(mem_axi4_0_aw_valid),
 .mem_axi4_0_aw_bits_id(mem_axi4_0_aw_bits_id),
 .mem_axi4_0_aw_bits_addr(mem_axi4_0_aw_bits_addr),
 .mem_axi4_0_aw_bits_len(mem_axi4_0_aw_bits_len),
 .mem_axi4_0_aw_bits_size(mem_axi4_0_aw_bits_size),
 .mem_axi4_0_aw_bits_burst(mem_axi4_0_aw_bits_burst),
 .mem_axi4_0_aw_bits_lock(mem_axi4_0_aw_bits_lock),
 .mem_axi4_0_aw_bits_cache(mem_axi4_0_aw_bits_cache),
 .mem_axi4_0_aw_bits_prot(mem_axi4_0_aw_bits_prot),
 .mem_axi4_0_aw_bits_qos(mem_axi4_0_aw_bits_qos),
 .mem_axi4_0_w_ready(mem_axi4_0_w_ready),
 .mem_axi4_0_w_valid(mem_axi4_0_w_valid),
 .mem_axi4_0_w_bits_data(mem_axi4_0_w_bits_data),
 .mem_axi4_0_w_bits_strb(mem_axi4_0_w_bits_strb),
 .mem_axi4_0_w_bits_last(mem_axi4_0_w_bits_last),
 .mem_axi4_0_b_ready(mem_axi4_0_b_ready),
 .mem_axi4_0_b_valid(mem_axi4_0_b_valid),
 .mem_axi4_0_b_bits_id(mem_axi4_0_b_bits_id),
 .mem_axi4_0_b_bits_resp(mem_axi4_0_b_bits_resp),
 .mem_axi4_0_ar_ready(mem_axi4_0_ar_ready),
 .mem_axi4_0_ar_valid(mem_axi4_0_ar_valid),
 .mem_axi4_0_ar_bits_id(mem_axi4_0_ar_bits_id),
 .mem_axi4_0_ar_bits_addr(mem_axi4_0_ar_bits_addr),
 .mem_axi4_0_ar_bits_len(mem_axi4_0_ar_bits_len),
 .mem_axi4_0_ar_bits_size(mem_axi4_0_ar_bits_size),
 .mem_axi4_0_ar_bits_burst(mem_axi4_0_ar_bits_burst),
 .mem_axi4_0_ar_bits_lock(mem_axi4_0_ar_bits_lock),
 .mem_axi4_0_ar_bits_cache(mem_axi4_0_ar_bits_cache),
 .mem_axi4_0_ar_bits_prot(mem_axi4_0_ar_bits_prot),
 .mem_axi4_0_ar_bits_qos(mem_axi4_0_ar_bits_qos),
 .mem_axi4_0_r_ready(mem_axi4_0_r_ready),
 .mem_axi4_0_r_valid(mem_axi4_0_r_valid),
 .mem_axi4_0_r_bits_id(mem_axi4_0_r_bits_id),
 .mem_axi4_0_r_bits_data(mem_axi4_0_r_bits_data),
 .mem_axi4_0_r_bits_resp(mem_axi4_0_r_bits_resp),
 .mem_axi4_0_r_bits_last(mem_axi4_0_r_bits_last),
 .mmio_axi4_0_aw_ready(mmio_axi4_0_aw_ready),
 .mmio_axi4_0_aw_valid(mmio_axi4_0_aw_valid),
 .mmio_axi4_0_aw_bits_id(mmio_axi4_0_aw_bits_id),
 .mmio_axi4_0_aw_bits_addr(mmio_axi4_0_aw_bits_addr),
 .mmio_axi4_0_aw_bits_len(mmio_axi4_0_aw_bits_len),
 .mmio_axi4_0_aw_bits_size(mmio_axi4_0_aw_bits_size),
 .mmio_axi4_0_aw_bits_burst(mmio_axi4_0_aw_bits_burst),
 .mmio_axi4_0_aw_bits_lock(mmio_axi4_0_aw_bits_lock),
 .mmio_axi4_0_aw_bits_cache(mmio_axi4_0_aw_bits_cache),
 .mmio_axi4_0_aw_bits_prot(mmio_axi4_0_aw_bits_prot),
 .mmio_axi4_0_aw_bits_qos(mmio_axi4_0_aw_bits_qos),
 .mmio_axi4_0_w_ready(mmio_axi4_0_w_ready),
 .mmio_axi4_0_w_valid(mmio_axi4_0_w_valid),
 .mmio_axi4_0_w_bits_data(mmio_axi4_0_w_bits_data),
 .mmio_axi4_0_w_bits_strb(mmio_axi4_0_w_bits_strb),
 .mmio_axi4_0_w_bits_last(mmio_axi4_0_w_bits_last),
 .mmio_axi4_0_b_ready(mmio_axi4_0_b_ready),
 .mmio_axi4_0_b_valid(mmio_axi4_0_b_valid),
 .mmio_axi4_0_b_bits_id(mmio_axi4_0_b_bits_id),
 .mmio_axi4_0_b_bits_resp(mmio_axi4_0_b_bits_resp),
 .mmio_axi4_0_ar_ready(mmio_axi4_0_ar_ready),
 .mmio_axi4_0_ar_valid(mmio_axi4_0_ar_valid),
 .mmio_axi4_0_ar_bits_id(mmio_axi4_0_ar_bits_id),
 .mmio_axi4_0_ar_bits_addr(mmio_axi4_0_ar_bits_addr),
 .mmio_axi4_0_ar_bits_len(mmio_axi4_0_ar_bits_len),
 .mmio_axi4_0_ar_bits_size(mmio_axi4_0_ar_bits_size),
 .mmio_axi4_0_ar_bits_burst(mmio_axi4_0_ar_bits_burst),
 .mmio_axi4_0_ar_bits_lock(mmio_axi4_0_ar_bits_lock),
 .mmio_axi4_0_ar_bits_cache(mmio_axi4_0_ar_bits_cache),
 .mmio_axi4_0_ar_bits_prot(mmio_axi4_0_ar_bits_prot),
 .mmio_axi4_0_ar_bits_qos(mmio_axi4_0_ar_bits_qos),
 .mmio_axi4_0_r_ready(mmio_axi4_0_r_ready),
 .mmio_axi4_0_r_valid(mmio_axi4_0_r_valid),
 .mmio_axi4_0_r_bits_id(mmio_axi4_0_r_bits_id),
 .mmio_axi4_0_r_bits_data(mmio_axi4_0_r_bits_data),
 .mmio_axi4_0_r_bits_resp(mmio_axi4_0_r_bits_resp),
 .mmio_axi4_0_r_bits_last(mmio_axi4_0_r_bits_last),
 .l2_frontend_bus_axi4_0_aw_ready(),
 .l2_frontend_bus_axi4_0_aw_valid('0),
 .l2_frontend_bus_axi4_0_aw_bits_id('0),
 .l2_frontend_bus_axi4_0_aw_bits_addr('0),
 .l2_frontend_bus_axi4_0_aw_bits_len('0),
 .l2_frontend_bus_axi4_0_aw_bits_size('0),
 .l2_frontend_bus_axi4_0_aw_bits_burst('0),
 .l2_frontend_bus_axi4_0_aw_bits_lock('0),
 .l2_frontend_bus_axi4_0_aw_bits_cache('0),
 .l2_frontend_bus_axi4_0_aw_bits_prot('0),
 .l2_frontend_bus_axi4_0_aw_bits_qos('0),
 .l2_frontend_bus_axi4_0_w_ready(),
 .l2_frontend_bus_axi4_0_w_valid('0),
 .l2_frontend_bus_axi4_0_w_bits_data('0),
 .l2_frontend_bus_axi4_0_w_bits_strb('0),
 .l2_frontend_bus_axi4_0_w_bits_last('0),
 .l2_frontend_bus_axi4_0_b_ready('0),
 .l2_frontend_bus_axi4_0_b_valid(),
 .l2_frontend_bus_axi4_0_b_bits_id(),
 .l2_frontend_bus_axi4_0_b_bits_resp(),
 .l2_frontend_bus_axi4_0_ar_ready(),
 .l2_frontend_bus_axi4_0_ar_valid('0),
 .l2_frontend_bus_axi4_0_ar_bits_id('0),
 .l2_frontend_bus_axi4_0_ar_bits_addr('0),
 .l2_frontend_bus_axi4_0_ar_bits_len('0),
 .l2_frontend_bus_axi4_0_ar_bits_size('0),
 .l2_frontend_bus_axi4_0_ar_bits_burst('0),
 .l2_frontend_bus_axi4_0_ar_bits_lock('0),
 .l2_frontend_bus_axi4_0_ar_bits_cache('0),
 .l2_frontend_bus_axi4_0_ar_bits_prot('0),
 .l2_frontend_bus_axi4_0_ar_bits_qos('0),
 .l2_frontend_bus_axi4_0_r_ready('0),
 .l2_frontend_bus_axi4_0_r_valid(),
 .l2_frontend_bus_axi4_0_r_bits_id(),
 .l2_frontend_bus_axi4_0_r_bits_data(),
 .l2_frontend_bus_axi4_0_r_bits_resp(),
 .l2_frontend_bus_axi4_0_r_bits_last(),
 .interrupts('0)
 );
 axi64_to_wb32 m_bridge (
 .clk(clk),
 .rst(rst),
 .aw_valid(mem_axi4_0_aw_valid),
 .aw_ready(mem_axi4_0_aw_ready),
 .aw_id(mem_axi4_0_aw_bits_id),
 .aw_addr(mem_axi4_0_aw_bits_addr),
 .aw_len(mem_axi4_0_aw_bits_len),
 .aw_size(mem_axi4_0_aw_bits_size),
 .aw_burst(mem_axi4_0_aw_bits_burst),
 .aw_lock(mem_axi4_0_aw_bits_lock),
 .w_valid(mem_axi4_0_w_valid),
 .w_ready(mem_axi4_0_w_ready),
 .w_data(mem_axi4_0_w_bits_data),
 .w_strb(mem_axi4_0_w_bits_strb),
 .w_last(mem_axi4_0_w_bits_last),
 .b_valid(mem_axi4_0_b_valid),
 .b_ready(mem_axi4_0_b_ready),
 .b_id(mem_axi4_0_b_bits_id),
 .b_resp(mem_axi4_0_b_bits_resp),
 .ar_valid(mem_axi4_0_ar_valid),
 .ar_ready(mem_axi4_0_ar_ready),
 .ar_id(mem_axi4_0_ar_bits_id),
 .ar_addr(mem_axi4_0_ar_bits_addr),
 .ar_len(mem_axi4_0_ar_bits_len),
 .ar_size(mem_axi4_0_ar_bits_size),
 .ar_burst(mem_axi4_0_ar_bits_burst),
 .ar_lock(mem_axi4_0_ar_bits_lock),
 .r_valid(mem_axi4_0_r_valid),
 .r_ready(mem_axi4_0_r_ready),
 .r_id(mem_axi4_0_r_bits_id),
 .r_data(mem_axi4_0_r_bits_data),
 .r_resp(mem_axi4_0_r_bits_resp),
 .r_last(mem_axi4_0_r_bits_last),
 .wb_cyc(m_cyc),
 .wb_stb(m_stb),
 .wb_we(m_we),
 .wb_adr(m_adr),
 .wb_dat_w(m_dat_w),
 .wb_sel(m_sel),
 .wb_dat_r(m_dat_r),
 .wb_ack(m_ack),
 .wb_err(m_err)
 );
 axi64_to_wb32 u_bridge (
 .clk(clk),
 .rst(rst),
 .aw_valid(mmio_axi4_0_aw_valid),
 .aw_ready(mmio_axi4_0_aw_ready),
 .aw_id(mmio_axi4_0_aw_bits_id),
 .aw_addr({1'b0,mmio_axi4_0_aw_bits_addr}),
 .aw_len(mmio_axi4_0_aw_bits_len),
 .aw_size(mmio_axi4_0_aw_bits_size),
 .aw_burst(mmio_axi4_0_aw_bits_burst),
 .aw_lock(mmio_axi4_0_aw_bits_lock),
 .w_valid(mmio_axi4_0_w_valid),
 .w_ready(mmio_axi4_0_w_ready),
 .w_data(mmio_axi4_0_w_bits_data),
 .w_strb(mmio_axi4_0_w_bits_strb),
 .w_last(mmio_axi4_0_w_bits_last),
 .b_valid(mmio_axi4_0_b_valid),
 .b_ready(mmio_axi4_0_b_ready),
 .b_id(mmio_axi4_0_b_bits_id),
 .b_resp(mmio_axi4_0_b_bits_resp),
 .ar_valid(mmio_axi4_0_ar_valid),
 .ar_ready(mmio_axi4_0_ar_ready),
 .ar_id(mmio_axi4_0_ar_bits_id),
 .ar_addr({1'b0,mmio_axi4_0_ar_bits_addr}),
 .ar_len(mmio_axi4_0_ar_bits_len),
 .ar_size(mmio_axi4_0_ar_bits_size),
 .ar_burst(mmio_axi4_0_ar_bits_burst),
 .ar_lock(mmio_axi4_0_ar_bits_lock),
 .r_valid(mmio_axi4_0_r_valid),
 .r_ready(mmio_axi4_0_r_ready),
 .r_id(mmio_axi4_0_r_bits_id),
 .r_data(mmio_axi4_0_r_bits_data),
 .r_resp(mmio_axi4_0_r_bits_resp),
 .r_last(mmio_axi4_0_r_bits_last),
 .wb_cyc(u_cyc),
 .wb_stb(u_stb),
 .wb_we(u_we),
 .wb_adr(u_adr),
 .wb_dat_w(u_dat_w),
 .wb_sel(u_sel),
 .wb_dat_r(u_dat_r),
 .wb_ack(u_ack),
 .wb_err(u_err)
 );
endmodule
`default_nettype wire
