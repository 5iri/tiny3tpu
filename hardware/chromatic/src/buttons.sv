`default_nettype none
module buttons #(
    parameter integer WIDTH = 8,
    parameter integer DEBOUNCE_BITS = 16
)(
    input wire clk, reset,
    input wire [WIDTH-1:0] raw,
    output reg [WIDTH-1:0] held,
    output reg [WIDTH-1:0] pressed
);
    (* async_reg = "true" *) reg [WIDTH-1:0] sync1, sync2;
    reg [DEBOUNCE_BITS-1:0] count [0:WIDTH-1];
    integer i;
    always @(posedge clk) begin
        if(reset) begin
            sync1 <= 0; sync2 <= 0; held <= 0; pressed <= 0;
            for(i=0;i<WIDTH;i=i+1) count[i] <= 0;
        end else begin
            sync1 <= raw; sync2 <= sync1; pressed <= 0;
            for(i=0;i<WIDTH;i=i+1) begin
                if(sync2[i] == held[i]) count[i] <= 0;
                else if(&count[i]) begin
                    held[i] <= sync2[i]; pressed[i] <= sync2[i]; count[i] <= 0;
                end else count[i] <= count[i]+1'b1;
            end
        end
    end
endmodule
`default_nettype wire

