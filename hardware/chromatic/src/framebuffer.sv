`default_nettype none
module framebuffer(input wire clk,write_enable,
    input wire [15:0] write_address,
    input wire [3:0] write_data,
    input wire display_bank,
    input wire [14:0] read_address,
    output reg [3:0] read_data);
    (* ram_style="block", no_rw_check *) reg [3:0] memory [0:65535];
    always @(posedge clk) begin
        if(write_enable) memory[write_address]<=write_data;
        read_data<=memory[{display_bank,read_address}];
    end
endmodule
`default_nettype wire
