`default_nettype none
// Native 640x480 double buffer. Render two pixels per word; scan one per clock.
module kc705_hdmi_framebuffer #(parameter WIDTH=4)(
    input wire clk, write_enable,
    input wire [18:0] write_address,
    input wire [1:0] write_mask,
    input wire [2*WIDTH-1:0] write_data,
    input wire display_bank,
    input wire [17:0] read_address,
    input wire read_lane,
    output wire [WIDTH-1:0] read_data
);
    wire [2*WIDTH-1:0] pixel0,pixel1;
    wire [2*WIDTH-1:0] pair_data=read_bank ? pixel1 : pixel0;
    reg read_bank,lane_q;
    kc705_hdmi_ram #(.WIDTH(WIDTH)) bank0(.clk(clk),
        .write_enable(write_enable && !write_address[18]),.write_mask(write_mask),
        .write_address(write_address[17:0]),.write_data(write_data),
        .read_address(read_address),.read_data(pixel0));
    kc705_hdmi_ram #(.WIDTH(WIDTH)) bank1(.clk(clk),
        .write_enable(write_enable && write_address[18]),.write_mask(write_mask),
        .write_address(write_address[17:0]),.write_data(write_data),
        .read_address(read_address),.read_data(pixel1));
    always @(posedge clk) begin read_bank<=display_bank;lane_q<=read_lane;end
    assign read_data=lane_q ? pair_data[WIDTH+:WIDTH] : pair_data[0+:WIDTH];
endmodule
`default_nettype wire
