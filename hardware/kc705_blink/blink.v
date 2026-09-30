`default_nettype none

module blink (
    input  wire       clk_p,
    input  wire       clk_n,
    output wire [7:0] led
);
    wire clk_ibufg;
    wire clk;
    reg [28:0] counter = 29'd0;

    IBUFDS clock_input (.I(clk_p), .IB(clk_n), .O(clk_ibufg));
    BUFG clock_buffer (.I(clk_ibufg), .O(clk));

    always @(posedge clk)
        counter <= counter + 1'b1;

    // Walk across all eight LEDs every ~0.34 seconds at 200 MHz.
    assign led = 8'b00000001 << counter[28:26];
endmodule

`default_nettype wire
