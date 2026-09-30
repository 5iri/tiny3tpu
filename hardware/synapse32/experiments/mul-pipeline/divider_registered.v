`default_nettype none

// Exact iterative RV32 integer divider.
//
// Capture operands before classification/sign conversion, then perform one
// restoring-division step per clock. This keeps the divide
// datapath short enough for FPGA timing while retaining the RISC-V DIV/DIVU/
// REM/REMU corner-case behavior.
module divider (
    input wire clk,
    input wire rst,
    input wire start,
    input wire cancel,
    input wire signed_mode,
    input wire remainder_mode,
    input wire [31:0] dividend,
    input wire [31:0] divisor,
    output reg busy,
    output reg done,
    output reg [31:0] result
);

    reg [31:0] dividend_q;
    reg [31:0] divisor_q;
    reg [31:0] quotient_q;
    reg [32:0] remainder_q;
    reg dividend_negative_q;
    reg quotient_negative_q;
    reg signed_mode_q;
    reg remainder_mode_q;
    reg [5:0] count_q;
    reg setup_q;

    wire [32:0] trial_remainder = {remainder_q[31:0], dividend_q[31]};
    wire trial_subtract = trial_remainder >= {1'b0, divisor_q};
    wire [32:0] remainder_next = trial_subtract ?
                                  (trial_remainder - {1'b0, divisor_q}) :
                                  trial_remainder;
    wire [31:0] quotient_next = {quotient_q[30:0], trial_subtract};
    wire [31:0] quotient_signed = quotient_negative_q ?
                                   (~quotient_next + 32'd1) : quotient_next;
    wire [31:0] remainder_signed = dividend_negative_q ?
                                    (~remainder_next[31:0] + 32'd1) :
                                    remainder_next[31:0];

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            dividend_q <= 32'h0;
            divisor_q <= 32'h0;
            quotient_q <= 32'h0;
            remainder_q <= 33'h0;
            dividend_negative_q <= 1'b0;
            quotient_negative_q <= 1'b0;
            signed_mode_q <= 1'b0;
            remainder_mode_q <= 1'b0;
            count_q <= 6'h0;
            setup_q <= 1'b0;
            busy <= 1'b0;
            done <= 1'b0;
            result <= 32'h0;
        end else if (cancel) begin
            busy <= 1'b0;
            done <= 1'b0;
            setup_q <= 1'b0;
        end else if (start && !busy && !done) begin
            done <= 1'b0;
            busy <= 1'b1;
            setup_q <= 1'b1;
            count_q <= 6'b0;
            dividend_q <= dividend;
            divisor_q <= divisor;
            signed_mode_q <= signed_mode;
            remainder_mode_q <= remainder_mode;
        end else if (busy && setup_q) begin
            setup_q <= 1'b0;
            // RISC-V specifies all-one quotient and the original dividend
            // remainder for division by zero.
            if (divisor_q == 32'h0) begin
                result <= remainder_mode_q ? dividend_q : 32'hFFFFFFFF;
                done <= 1'b1;
                busy <= 1'b0;
            end else if (signed_mode_q && dividend_q == 32'h80000000 &&
                         divisor_q == 32'hFFFFFFFF) begin
                // Signed overflow: DIV returns INT_MIN, REM returns zero.
                result <= remainder_mode_q ? 32'h0 : 32'h80000000;
                done <= 1'b1;
                busy <= 1'b0;
            end else begin
                dividend_negative_q <= signed_mode_q && dividend_q[31];
                quotient_negative_q <= signed_mode_q && (dividend_q[31] ^ divisor_q[31]);
                dividend_q <= (signed_mode_q && dividend_q[31]) ?
                              (~dividend_q + 32'd1) : dividend_q;
                divisor_q <= (signed_mode_q && divisor_q[31]) ?
                             (~divisor_q + 32'd1) : divisor_q;
                quotient_q <= 32'h0;
                remainder_q <= 33'h0;
                count_q <= 6'h0;
                busy <= 1'b1;
            end
        end else if (busy) begin
            dividend_q <= {dividend_q[30:0], 1'b0};
            quotient_q <= quotient_next;
            remainder_q <= remainder_next;

            if (count_q == 6'd31) begin
                busy <= 1'b0;
                done <= 1'b1;
                result <= remainder_mode_q ? remainder_signed : quotient_signed;
            end else begin
                count_q <= count_q + 6'd1;
            end
        end else begin
            // Keep result stable for the cycle in which the consumer retires
            // the instruction, then turn done into a one-shot indication.
            done <= 1'b0;
        end
    end

endmodule

`default_nettype wire
