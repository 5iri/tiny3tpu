`timescale 1ns/1ps
`default_nettype none
// Standalone KC705 renderer. Application and scanout share the selected clock.
module kc705_hdmi_top #(
    parameter CPU_DRIVEN=0,
    parameter CPU_FRAMEBUFFER=0,
    parameter VIDEO_720P=0,
    parameter CPU_BOOT_WORDS=65536,
    parameter FRAME_WIDTH=160,
    parameter FRAME_HEIGHT=120,
`ifdef VEXRISCV_BOOT_HEX
    parameter BOOT_HEX=`VEXRISCV_BOOT_HEX
`else
    parameter BOOT_HEX=""
`endif
) (
    input wire clk_p, clk_n, reset_button,
    input wire [2:0] user_buttons, // center, north, east
    input wire test_pattern_switch,
    input wire speed_down_switch,
    input wire rotate_left_switch,
    inout wire i2c_scl, i2c_sda,
    output wire i2c_mux_reset_n,
    output wire [15:0] hdmi_d,
    output wire [1:0] hdmi_unused,
    output wire hdmi_clk, hdmi_de, hdmi_hsync, hdmi_vsync, hdmi_spdif,
    output wire [7:0] led
);
    wire clk200, clk_pixel_unbuf, clk_pixel, feedback, locked;
    localparam CLOCK_HZ=VIDEO_720P ? 74250000 : 25200000;
    IBUFDS #(.IOSTANDARD("LVDS")) oscillator (.I(clk_p), .IB(clk_n), .O(clk200));
    generate if(VIDEO_720P)begin: hd_clock
        // UG472: fractional feedback in 1/8 increments. 200/10*37.125/10
        // gives exactly 74.25 MHz; PFD=20 MHz, VCO=742.5 MHz.
        MMCME2_ADV #(.BANDWIDTH("OPTIMIZED"),.CLKIN1_PERIOD(5.0),
            .DIVCLK_DIVIDE(10),.CLKFBOUT_MULT_F(37.125),.CLKFBOUT_PHASE(0.0),
            .CLKOUT0_DIVIDE_F(10.0),.CLKOUT0_DUTY_CYCLE(0.5),.CLKOUT0_PHASE(0.0),
            .REF_JITTER1(0.01)) pixel_mmcm(
            .CLKIN1(clk200),.CLKIN2(1'b0),.CLKINSEL(1'b1),
            .CLKFBIN(feedback),.CLKFBOUT(feedback),.CLKOUT0(clk_pixel_unbuf),
            .LOCKED(locked),.PWRDWN(1'b0),.RST(reset_button),
            .DADDR(7'b0),.DCLK(1'b0),.DEN(1'b0),.DI(16'b0),.DWE(1'b0),
            .PSCLK(1'b0),.PSEN(1'b0),.PSINCDEC(1'b0));
    end else begin: vga_clock
    // AMD DS182 table 42, -2 at 1.0 V: PFD 19..500 MHz, VCO 800..1866 MHz.
    // PFD = 200/10 = 20 MHz; VCO = 20*63 = 1260 MHz; output = 1260/50.
    PLLE2_ADV #(.BANDWIDTH("OPTIMIZED"), .CLKIN1_PERIOD(5.0),
        .DIVCLK_DIVIDE(10), .CLKFBOUT_MULT(63), .CLKFBOUT_PHASE(0.0),
        .CLKOUT0_DIVIDE(50), .CLKOUT0_DUTY_CYCLE(0.5), .CLKOUT0_PHASE(0.0),
        .REF_JITTER1(0.01)) pixel_pll (
        .CLKIN1(clk200), .CLKIN2(1'b0), .CLKINSEL(1'b1),
        .CLKFBIN(feedback), .CLKFBOUT(feedback), .CLKOUT0(clk_pixel_unbuf),
        .LOCKED(locked), .PWRDWN(1'b0), .RST(reset_button),
        .DADDR(7'b0), .DCLK(1'b0), .DEN(1'b0), .DI(16'b0), .DWE(1'b0));
    end endgenerate
    BUFG pixel_buffer (.I(clk_pixel_unbuf), .O(clk_pixel));
    (* async_reg="true" *) reg [3:0] reset_pipe=4'b1111;
    wire async_reset=reset_button || !locked;
    always @(posedge clk_pixel or posedge async_reset)
        if(async_reset) reset_pipe<=4'b1111;
        else reset_pipe<={reset_pipe[2:0],1'b0};
    wire reset=reset_pipe[3];

    wire [7:0] held, pressed;
    buttons #(.DEBOUNCE_BITS(18)) controls (
        .clk(clk_pixel), .reset(reset),
        .raw({2'b00,user_buttons[2],rotate_left_switch,speed_down_switch,user_buttons[1],1'b0,user_buttons[0]}),
        .held(held), .pressed(pressed));
    (* async_reg="true" *) reg [1:0] pattern_sync=0;
    always @(posedge clk_pixel) begin
        if(reset) pattern_sync<=0;
        else pattern_sync<={pattern_sync[0],test_pattern_switch};
    end
    wire configured, init_error;
    kc705_hdmi_init #(.CLOCK_HZ(CLOCK_HZ),.VIDEO_720P(VIDEO_720P)) initialization (
        .clk(clk_pixel), .reset(reset), .scl(i2c_scl), .sda(i2c_sda),
        .mux_reset_n(i2c_mux_reset_n), .configured(configured), .error(init_error));

    wire frame_tick, render_busy, display_valid, display_bank;
    wire [31:0] render_cycles;
    wire [15:0] frames;
    wire [7:0] display_phase;
    wire cpu_error;
    generate if(CPU_FRAMEBUFFER)begin: pixel_path
        wire [31:0] pixel_frames,pixel_tag,exit_code;
        wire fault,exit_valid;
        assign frames=pixel_frames[15:0];assign display_phase=pixel_tag[7:0];
        assign render_cycles=0;assign cpu_error=fault || (exit_valid && exit_code!=0);
        kc705_hdmi_pixel_system #(.BOOT_HEX(BOOT_HEX),.BOOT_WORDS(CPU_BOOT_WORDS),
            .FRAME_WIDTH(FRAME_WIDTH),.FRAME_HEIGHT(FRAME_HEIGHT),.VIDEO_720P(VIDEO_720P)) system(
            .clk(clk_pixel),.reset(reset),.enable(configured),.test_pattern(pattern_sync[1]),
            .hdmi_d(hdmi_d),.de(hdmi_de),.hsync(hdmi_hsync),.vsync(hdmi_vsync),
            .frame_tick(frame_tick),.pending(render_busy),.display_valid(display_valid),
            .display_bank(display_bank),.frames(pixel_frames),.display_tag(pixel_tag),
            .fault(fault),.exit_valid(exit_valid),.exit_code(exit_code),.report_valid(),.report_data());
    end else if(CPU_DRIVEN)begin: cpu_path
        kc705_hdmi_cpu_system #(.BOOT_HEX(BOOT_HEX)) system(
            .clk(clk_pixel),.reset(reset),.enable(configured),.held(held),.pressed(pressed),
            .test_pattern(pattern_sync[1]),.hdmi_d(hdmi_d),.de(hdmi_de),
            .hsync(hdmi_hsync),.vsync(hdmi_vsync),.frame_tick(frame_tick),
            .render_busy(render_busy),.display_valid(display_valid),.display_bank(display_bank),
            .render_cycles(render_cycles),.frames(frames),.display_phase(display_phase),
            .cpu_error(cpu_error),.fault(),.exit_valid(),.exit_code(),.report_valid(),.report_data());
    end else begin: standalone_path
        assign cpu_error=0;
    kc705_hdmi_display display (
        .clk(clk_pixel), .reset(reset), .enable(configured), .held(held), .pressed(pressed),
        .command_start(1'b0),.command_phase(8'd0),.command_ready(),
        .vertex_write(1'b0),.vertex_index(12'd0),.vertex_data(28'd0),
        .test_pattern(pattern_sync[1]), .hdmi_d(hdmi_d), .de(hdmi_de),
        .hsync(hdmi_hsync), .vsync(hdmi_vsync), .frame_tick(frame_tick),
        .render_busy(render_busy), .display_valid(display_valid), .display_bank(display_bank),
        .render_cycles(render_cycles), .frames(frames), .display_phase(display_phase));
    end endgenerate
    // Data/sync launch at the positive pixel edge. ADV7511 samples on the
    // rising forwarded edge, one half-cycle later (19.841/6.734 ns VGA/720p).
    // This phase choice is not a substitute for board I/O timing qualification.
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE"), .INIT(1'b0), .SRTYPE("SYNC")) pixel_forward (
        .C(clk_pixel), .CE(1'b1), .D1(1'b0), .D2(1'b1), .Q(hdmi_clk), .R(1'b0), .S(1'b0));
    assign hdmi_unused=2'b00;
    assign hdmi_spdif=1'b0;
    assign led={frames[5],pattern_sync[1],display_bank,render_busy,display_valid,(init_error|cpu_error),configured,locked};
endmodule
`default_nettype wire
