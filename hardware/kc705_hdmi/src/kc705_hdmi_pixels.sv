`default_nettype none
// CPU-authored RGB565 frames. The aperture always addresses the back bank.
// Full frames are uploaded in order, then committed; writes are rejected until
// the commit publishes at vertical blank. No scene-specific rendering logic.
module kc705_hdmi_pixels #(
    parameter WIDTH=160, HEIGHT=120, SCALE=4, VIDEO_720P=0
)(
    input wire clk,reset,enable,test_pattern,
    input wire req_valid,output wire req_ready,
    input wire req_write,input wire [31:0] req_addr,req_wdata,
    input wire [3:0] req_wstrb,
    output reg resp_valid,input wire resp_ready,
    output reg [31:0] resp_rdata,output reg resp_error,
    output reg [15:0] hdmi_d,
    output reg de,hsync,vsync,
    output wire frame_tick,
    output reg display_bank,display_valid,pending,
    output reg [31:0] frames,display_tag
);
    localparam WORDS=WIDTH*HEIGHT/2;
    localparam ADDR_BITS=$clog2(WORDS);
    localparam H_ACTIVE=VIDEO_720P ? 1280 : 640, V_ACTIVE=VIDEO_720P ? 720 : 480;
    localparam H_TOTAL=VIDEO_720P ? 1650 : 800, V_TOTAL=VIDEO_720P ? 750 : 525;
    localparam H_SYNC_START=VIDEO_720P ? 1390 : 656, H_SYNC_END=VIDEO_720P ? 1430 : 752;
    localparam V_SYNC_START=VIDEO_720P ? 725 : 490, V_SYNC_END=VIDEO_720P ? 730 : 492;
    function automatic integer gcd(input integer a,b);
        integer t;
        begin while(b!=0)begin t=a%b;a=b;b=t;end gcd=a;end
    endfunction
    // Reduce the ratios at elaboration: 480/1280 = 270/720 = 3/8.
    // This gives exact aspect-preserving scaling with add/shift hardware.
    localparam X_MUL=WIDTH/gcd(WIDTH,H_ACTIVE), X_DIV=H_ACTIVE/gcd(WIDTH,H_ACTIVE);
    localparam Y_MUL=HEIGHT/gcd(HEIGHT,V_ACTIVE), Y_DIV=V_ACTIVE/gcd(HEIGHT,V_ACTIVE);
    initial begin
        if(WIDTH%2!=0 || WIDTH*V_ACTIVE!=HEIGHT*H_ACTIVE || WIDTH>H_ACTIVE || HEIGHT>V_ACTIVE)
            $error("Framebuffer must be even-width, fit the raster and preserve its aspect ratio");
    end
    (* ram_style="block" *) reg [31:0] bank0[0:WORDS-1];
    (* ram_style="block" *) reg [31:0] bank1[0:WORDS-1];
    reg [31:0] upload_count,queued_tag;
    reg [$clog2(H_TOTAL)-1:0] h_count;
    reg [$clog2(V_TOTAL)-1:0] v_count;
    wire active=h_count<H_ACTIVE && v_count<V_ACTIVE;
    assign frame_tick=h_count==0 && v_count==V_ACTIVE;
    assign req_ready=!reset && !resp_valid;
    wire transaction=req_valid && req_ready;
    wire control=req_addr[31:8]==24'h400000;
    wire pixels=req_addr>=32'h40100000 && req_addr<32'h40100000+WORDS*4;
    wire [31:0] write_index=(req_addr-32'h40100000)>>2;
    wire pixel_write=transaction && req_write && req_wstrb==15 &&
        req_addr[1:0]==0 && pixels && !pending && write_index==upload_count;
    // Memory arrays have no reset; display_valid hides them until a complete
    // CPU upload has been committed. Writes never touch the visible bank.
    always @(posedge clk) begin
        if(pixel_write && display_bank) bank0[write_index[ADDR_BITS-1:0]]<=req_wdata;
        if(pixel_write && !display_bank) bank1[write_index[ADDR_BITS-1:0]]<=req_wdata;
    end
    always @(posedge clk) begin
        if(reset)begin
            h_count<=0;v_count<=0;resp_valid<=0;resp_rdata<=0;resp_error<=0;
            upload_count<=0;queued_tag<=0;display_bank<=0;display_valid<=0;
            pending<=0;frames<=0;display_tag<=0;
        end else begin
            if(h_count==H_TOTAL-1)begin
                h_count<=0;v_count<=v_count==V_TOTAL-1 ? 0 : v_count+1'b1;
            end else h_count<=h_count+1'b1;
            if(frame_tick && pending)begin
                display_bank<=!display_bank;display_valid<=1;pending<=0;
                frames<=frames+1'b1;display_tag<=queued_tag;
            end
            if(resp_valid && resp_ready)resp_valid<=0;
            if(transaction)begin
                resp_valid<=1;resp_rdata<=0;resp_error<=0;
                if(req_addr[1:0]!=0 || (req_write && req_wstrb!=15))resp_error<=1;
                else if(req_write)begin
                    if(pixel_write)upload_count<=upload_count+1'b1;
                    else if(control && req_addr[7:0]==8'h08 && !pending && upload_count==WORDS)begin
                        pending<=1;queued_tag<=req_wdata;upload_count<=0;
                    end else resp_error<=1;
                end else if(control)begin
                    case(req_addr[7:0])
                        8'h00:resp_rdata<=32'h50464231; // PFB1, distinct from the vertex ABI
                        8'h04:resp_rdata<={28'd0,display_bank,display_valid,pending,!pending};
                        8'h0c:resp_rdata<=upload_count;
                        8'h10:resp_rdata<=WIDTH;
                        8'h14:resp_rdata<=HEIGHT;
                        8'h18:resp_rdata<=WORDS;
                        8'h1c:resp_rdata<=frames;
                        8'h20:resp_rdata<=display_tag;
                        8'h24:resp_rdata<=32'd565;
                        8'h28:resp_rdata<=H_ACTIVE;
                        8'h2c:resp_rdata<=V_ACTIVE;
                        8'h30:resp_rdata<=VIDEO_720P ? 74250000 : 25200000;
                        default:resp_error<=1;
                    endcase
                end else resp_error<=1;
            end
        end
    end

    // One-cycle synchronous memory read, including noninteger enlargement.
    // Spell the 3/8 scaler as shift/add. Yosys 0.63's DSP pre-adder packer
    // incorrectly absorbs the shared raster-counter increment with '* 3',
    // leaving the counter undriven. This form stays in fabric arithmetic.
    wire [31:0] scaled_x=X_MUL==3 ? 32'(h_count)+(32'(h_count)<<1) : 32'(h_count)*X_MUL;
    wire [31:0] scaled_y=Y_MUL==3 ? 32'(v_count)+(32'(v_count)<<1) : 32'(v_count)*Y_MUL;
    wire [31:0] pixel_index=active ? (scaled_y/Y_DIV)*WIDTH+scaled_x/X_DIV : 0;
    wire [ADDR_BITS-1:0] read_index=ADDR_BITS'(pixel_index>>1);
    reg [31:0] pair0,pair1;
    reg bank_q,lane_q,valid_q,active_q,hs_q,vs_q,odd_q,pattern_q;
    reg [2:0] bar_q;
    wire [31:0] pair=bank_q ? pair1 : pair0;
    wire [15:0] pixel=lane_q ? pair[31:16] : pair[15:0];
    (* async_reg="true" *) reg enable_meta,enable_sync,pattern_meta,pattern_sync;
    reg video_enabled,pattern_enabled;
    always @(posedge clk)begin
        pair0<=bank0[read_index];pair1<=bank1[read_index];
        if(reset)begin
            enable_meta<=0;enable_sync<=0;pattern_meta<=0;pattern_sync<=0;
            video_enabled<=0;pattern_enabled<=0;bank_q<=0;lane_q<=0;valid_q<=0;
            active_q<=0;hs_q<=!VIDEO_720P;vs_q<=!VIDEO_720P;odd_q<=0;pattern_q<=0;bar_q<=0;
        end else begin
            enable_meta<=enable;enable_sync<=enable_meta;
            pattern_meta<=test_pattern;pattern_sync<=pattern_meta;
            if(h_count==H_TOTAL-1 && v_count==V_TOTAL-1)begin
                video_enabled<=enable_sync;pattern_enabled<=pattern_sync;
            end
            bank_q<=display_bank;lane_q<=pixel_index[0];valid_q<=display_valid;
            active_q<=active && video_enabled;
            hs_q<=(h_count>=H_SYNC_START && h_count<H_SYNC_END) ^ !VIDEO_720P;
            vs_q<=(v_count>=V_SYNC_START && v_count<V_SYNC_END) ^ !VIDEO_720P;
            odd_q<=h_count[0];pattern_q<=pattern_enabled;
            bar_q<=3'(32'(h_count)/(H_ACTIVE/8));
        end
    end
    reg [7:0] red,green,blue;
    always @* begin
        red=0;green=0;blue=0;
        if(pattern_q)begin
            case(bar_q)
                0:begin red=255;green=255;blue=255;end
                1:begin red=255;green=255;end
                2:begin green=255;blue=255;end
                3:green=255;
                4:begin red=255;blue=255;end
                5:red=255;
                6:blue=255;
                default:begin end
            endcase
        end else if(active_q && valid_q)begin
            red={pixel[15:11],pixel[15:13]};
            green={pixel[10:5],pixel[10:9]};
            blue={pixel[4:0],pixel[4:2]};
        end
    end
    function automatic [23:0] rgb_to_ycc(input [7:0] r8,g8,b8);
        integer r,g,b,y,cb,cr;
        begin
            r={24'd0,r8};g={24'd0,g8};b={24'd0,b8};
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
    always @(posedge clk)begin
        if(reset)begin
            hdmi_d<=16'h8010;de<=0;hsync<=!VIDEO_720P;vsync<=!VIDEO_720P;
            even_y<=16;even_cb<=128;even_cr<=128;odd_y<=16;odd_cr<=128;
            even_de<=0;even_hs<=!VIDEO_720P;even_vs<=!VIDEO_720P;
            odd_de<=0;odd_hs<=!VIDEO_720P;odd_vs<=!VIDEO_720P;
        end else if(odd_q)begin
            hdmi_d<={cb_sum[8:1],even_y};de<=even_de;hsync<=even_hs;vsync<=even_vs;
            odd_y<=ycc[23:16];odd_cr<=cr_sum[8:1];
            odd_de<=active_q;odd_hs<=hs_q;odd_vs<=vs_q;
        end else begin
            hdmi_d<={odd_cr,odd_y};de<=odd_de;hsync<=odd_hs;vsync<=odd_vs;
            even_y<=ycc[23:16];even_cb<=ycc[15:8];even_cr<=ycc[7:0];
            even_de<=active_q;even_hs<=hs_q;even_vs<=vs_q;
        end
    end
endmodule
`default_nettype wire
