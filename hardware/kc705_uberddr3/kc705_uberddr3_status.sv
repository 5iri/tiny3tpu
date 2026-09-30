`default_nettype none
module kc705_uberddr3_status #(
    // 2^33 / 100 MHz = 85.9 seconds, including initialization and full BIST.
    parameter TIMER_BITS = 34
) (
    input wire clk, rst_n, done,
    input wire [31:0] debug,
    output reg passed, failed
);
    initial begin passed = 0; failed = 0; end
    reg [TIMER_BITS-1:0] elapsed = 0;
    always @(posedge clk) begin
        if (!rst_n) begin
            elapsed <= 0;
            passed <= 0;
            failed <= 0;
        end else begin
            // Failure is sticky, including across the controller's own retries.
            if (debug[31] || (!passed && elapsed[TIMER_BITS-1])) begin
                failed <= 1;
                passed <= 0;
            end else if (!failed && done && debug[30]) passed <= 1;
            if (!passed && !failed) elapsed <= elapsed + 1'b1;
        end
    end
endmodule
`default_nettype wire
