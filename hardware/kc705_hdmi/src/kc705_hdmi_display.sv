`default_nettype none
// One 25.2 MHz domain: render to the back BRAM bank, publish in vertical blank,
// and scan native rendered pixels into 640x480p60 (800x525 total).
// KC705 board HDMI_D: Y in bits7:0, paired Cb/Cr in bits15:8.
// This is the board bus order used by ADI's KC705 axi_hdmi_tx reference.
module kc705_hdmi_display #(parameter CPU_DRIVEN=0)(
    input wire clk, reset, enable,
    input wire [7:0] held, pressed,
    input wire test_pattern,
    input wire command_start,vertex_write,
    input wire [7:0] command_phase,
    input wire [11:0] vertex_index,
    input wire [27:0] vertex_data,
    output wire command_ready,
    output reg [15:0] hdmi_d,
    output reg de, hsync, vsync,
    output wire frame_tick, render_busy, display_valid, display_bank,
    output wire [31:0] render_cycles,
    output wire [15:0] frames,
    output wire [7:0] display_phase
);
    localparam PIXEL_BITS=CPU_DRIVEN ? 6 : 4;
    reg [9:0] h_count, v_count;
    wire active=(h_count<640 && v_count<480);
    wire [9:0] source_x=active ? h_count : 10'd0;
    wire [8:0] source_y=active ? v_count[8:0] : 9'd0;
    wire [17:0] read_address=({9'b0,source_y}<<8)+({9'b0,source_y}<<6)+{9'b0,source_x[9:1]};
    assign frame_tick=(h_count==0 && v_count==480);
    always @(posedge clk) begin
        if(reset) begin h_count<=0;v_count<=0;end
        else if(h_count==799) begin
            h_count<=0;v_count<=v_count==524 ? 10'd0 : v_count+1'b1;
        end else h_count<=h_count+1'b1;
    end

    // Configuration and pattern changes become visible only on a frame edge.
    (* async_reg="true" *) reg enable_meta, enable_sync, pattern_meta, pattern_sync;
    reg video_enabled, pattern_enabled;
    always @(posedge clk) begin
        if(reset) begin
            enable_meta<=0;enable_sync<=0;pattern_meta<=0;pattern_sync<=0;
            video_enabled<=0;pattern_enabled<=0;
        end else begin
            enable_meta<=enable;enable_sync<=enable_meta;
            pattern_meta<=test_pattern;pattern_sync<=pattern_meta;
            if(h_count==799 && v_count==524) begin
                video_enabled<=enable_sync;pattern_enabled<=pattern_sync;
            end
        end
    end

    wire render_start, render_done, paused, reverse;
    wire [7:0] phase;
    wire [2:0] speed;
    wire [31:0] completed_cycles;
    wire write_enable;
    wire [17:0] write_address;
    wire [1:0] write_mask;
    wire [2*PIXEL_BITS-1:0] write_data;
    wire [PIXEL_BITS-1:0] pixel;
    generate if(CPU_DRIVEN)begin: cpu_scene
        assign paused=0;assign reverse=0;assign speed=1;
        kc705_hdmi_cpu_scene scene_control(
            .clk(clk),.reset(reset),.frame_tick(frame_tick),.render_done(render_done),
            .command_start(command_start),.command_phase(command_phase),.command_ready(command_ready),
            .render_start(render_start),.display_bank(display_bank),.display_valid(display_valid),
            .phase(phase),.display_phase(display_phase),.last_cycles(completed_cycles),.frames(frames));
    end else begin: autonomous_scene
        assign command_ready=0;
    scene scene_control(
        .clk(clk),.reset(reset),.frame_tick(frame_tick),.render_done(render_done),
        .held(held),.pressed(pressed),.render_start(render_start),
        .display_bank(display_bank),.display_valid(display_valid),
        .phase(phase),.display_phase(display_phase),.paused(paused),.reverse(reverse),
        .speed(speed),.last_cycles(completed_cycles),.frames(frames));
    end endgenerate
    kc705_hdmi_renderer #(.CPU_DRIVEN(CPU_DRIVEN)) renderer(
        .clk(clk),.reset(reset),.start(render_start),.phase(phase),
        .vertex_write(vertex_write),.vertex_index(vertex_index),.vertex_data(vertex_data),
        .busy(render_busy),.done(render_done),.write_enable(write_enable),
        .write_address(write_address),.write_mask(write_mask),.write_data(write_data));
    kc705_hdmi_framebuffer #(.WIDTH(PIXEL_BITS)) frame_memory(
        .clk(clk),.write_enable(write_enable),.write_address({!display_bank,write_address}),
        .write_data(write_data),.write_mask(write_mask),.display_bank(display_bank),
        .read_address(read_address),.read_lane(source_x[0]),.read_data(pixel));

    // Metadata belongs to the published image. A new render can finish while
    // scanout displays the previous bank; never change the CYC overlay then.
    reg previous_bank, visible_paused, visible_reverse;
    reg [2:0] visible_speed;
    reg [31:0] visible_cycles;
    assign render_cycles=visible_cycles;
    always @(posedge clk) begin
        if(reset) begin
            previous_bank<=0;visible_paused<=0;visible_reverse<=0;
            visible_speed<=1;visible_cycles<=0;
        end else begin
            previous_bank<=display_bank;
            if(previous_bank!=display_bank) begin
                visible_cycles<=completed_cycles;visible_paused<=paused;
                visible_reverse<=reverse;visible_speed<=speed;
            end
        end
    end

    // Align coordinates and timing with the synchronous framebuffer read.
    reg [9:0] x0;
    reg [8:0] y0;
    reg active0,hs0,vs0,odd0,pattern0;
    reg [2:0] bar0;
    // Eight 80-pixel bars. Explicit boundaries avoid a general divider on
    // the scan counter's timing path; the blanking interval uses black.
    wire [2:0] bar_index=h_count<10'd80 ? 3'd0 :
        h_count<10'd160 ? 3'd1 : h_count<10'd240 ? 3'd2 :
        h_count<10'd320 ? 3'd3 : h_count<10'd400 ? 3'd4 :
        h_count<10'd480 ? 3'd5 : h_count<10'd560 ? 3'd6 : 3'd7;
    wire [5:0] palette_r,palette_g,palette_b;
    kc705_hdmi_palette #(.CPU_DRIVEN(CPU_DRIVEN)) palette(
        .x(x0),.y(y0),.display_valid(display_valid),.pixel(pixel),
        .red(palette_r),.green(palette_g),.blue(palette_b));
    always @(posedge clk) begin
        if(reset) begin
            x0<=0;y0<=0;active0<=0;hs0<=1;vs0<=1;
            odd0<=0;pattern0<=0;bar0<=0;
        end else begin
            x0<=h_count;y0<=v_count[8:0];
            active0<=active && video_enabled;
            hs0<=!(h_count>=656 && h_count<752);
            vs0<=!(v_count>=490 && v_count<492);
            odd0<=h_count[0];pattern0<=pattern_enabled;bar0<=bar_index;
        end
    end
    reg [5:0] red,green,blue;
    always @* begin
        red=0;green=0;blue=0;
        if(pattern0) begin
            case(bar0)
                0:begin red=63;green=63;blue=63;end
                1:begin red=63;green=63;end
                2:begin green=63;blue=63;end
                3:green=63;
                4:begin red=63;blue=63;end
                5:red=63;
                6:blue=63;
                default:begin end
            endcase
        end else if(active0) begin red=palette_r;green=palette_g;blue=palette_b;end
    end

    // Limited-range BT.601. Expanded six-bit palette components retain their
    // endpoints. All arithmetic is signed before the rounding arithmetic shift.
    function automatic [23:0] rgb_to_ycc(input [5:0] r6,g6,b6);
        integer r,g,b,y,cb,cr;
        begin
            r={24'd0,r6,r6[5:4]};g={24'd0,g6,g6[5:4]};b={24'd0,b6,b6[5:4]};
            y=((66*r+129*g+25*b+128)>>>8)+16;
            cb=((-38*r-74*g+112*b+128)>>>8)+128;
            cr=((112*r-94*g-18*b+128)>>>8)+128;
            rgb_to_ycc={8'(y),8'(cb),8'(cr)};
        end
    endfunction
    wire [23:0] ycc=rgb_to_ycc(red,green,blue);
    reg [7:0] even_y,even_cb,even_cr,odd_y,odd_cr;
    reg even_de,even_hs,even_vs,odd_de,odd_hs,odd_vs;
    wire [8:0] cb_sum={1'b0,even_cb}+{1'b0,ycc[15:8]}+9'd1;
    wire [8:0] cr_sum={1'b0,even_cr}+{1'b0,ycc[7:0]}+9'd1;
    // Delay both pixels by the same amount so chroma can be averaged across
    // each pair. The 800-pixel total keeps pair phase aligned between lines.
    always @(posedge clk) begin
        if(reset) begin
            hdmi_d<=16'h8010;de<=0;hsync<=1;vsync<=1;
            even_y<=16;even_cb<=128;even_cr<=128;odd_y<=16;odd_cr<=128;
            even_de<=0;even_hs<=1;even_vs<=1;odd_de<=0;odd_hs<=1;odd_vs<=1;
        end else if(odd0) begin
            hdmi_d<={cb_sum[8:1],even_y};de<=even_de;hsync<=even_hs;vsync<=even_vs;
            odd_y<=ycc[23:16];odd_cr<=cr_sum[8:1];
            odd_de<=active0;odd_hs<=hs0;odd_vs<=vs0;
        end else begin
            hdmi_d<={odd_cr,odd_y};de<=odd_de;hsync<=odd_hs;vsync<=odd_vs;
            even_y<=ycc[23:16];even_cb<=ycc[15:8];even_cr<=ycc[7:0];
            even_de<=active0;even_hs<=hs0;even_vs<=vs0;
        end
    end
endmodule
`default_nettype wire
