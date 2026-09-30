`default_nettype none
// RV32M multiplication with registered operands and four registered arithmetic
// steps. One operation may be outstanding. kind uses the MUL funct3 encoding:
// 00 low, 01 signed high, 10 signed/unsigned high, 11 unsigned high.
// start is accepted only when idle and done is low. cancel/reset wins completion.
// Datapath registers need no reset: result is valid only when done is asserted.
module synapse32_multiply (
    input wire clk, rst, start, cancel,
    input wire [1:0] kind,
    input wire [31:0] operand_a, operand_b,
    output reg busy, done,
    output reg [31:0] result
);
    reg [2:0] stage_q;
    reg [31:0] a_q, b_q;
    reg [1:0] kind_q;
    reg [31:0] p00_q, p01_q, p10_q, p11_q;
    reg [31:0] correction_q, high_sum_q, unsigned_high_q, low_result_q;
    reg [17:0] middle_q;
    reg [15:0] low_bits_q;
    wire take = start && !busy && !done && !cancel && !rst;
    wire negative_a = (kind_q == 1 || kind_q == 2) && a_q[31];
    wire negative_b = kind_q == 1 && b_q[31];

    // Use four unsigned 16x16 products rather than a long DSP cascade.
    always @(posedge clk) begin
        if (take) begin
            a_q <= operand_a;
            b_q <= operand_b;
            kind_q <= kind;
        end
        p00_q <= a_q[15:0] * b_q[15:0];
        p01_q <= a_q[15:0] * b_q[31:16];
        p10_q <= a_q[31:16] * b_q[15:0];
        p11_q <= a_q[31:16] * b_q[31:16];
        // Signed high = unsigned high - (a negative ? b : 0)
        //                                 - (b negative ? a : 0), modulo 2^32.
        correction_q <= (negative_a ? b_q : 32'b0) +
                        (negative_b ? a_q : 32'b0);
        middle_q <= {2'b0, p00_q[31:16]} + {2'b0, p01_q[15:0]} +
                    {2'b0, p10_q[15:0]};
        high_sum_q <= p11_q + {16'b0, p01_q[31:16]} + {16'b0, p10_q[31:16]};
        low_bits_q <= p00_q[15:0];
        unsigned_high_q <= high_sum_q + {30'b0, middle_q[17:16]};
        low_result_q <= {middle_q[15:0], low_bits_q};
        if (busy && stage_q == 4 && !cancel && !rst)
            result <= kind_q == 0 ? low_result_q : unsigned_high_q - correction_q;
    end

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            busy <= 0;
            done <= 0;
            stage_q <= 0;
        end else if (cancel) begin
            busy <= 0;
            done <= 0;
            stage_q <= 0;
        end else begin
            done <= 0;
            if (take) begin
                busy <= 1;
                stage_q <= 1;
            end else if (busy) begin
                if (stage_q == 4) begin
                    busy <= 0;
                    done <= 1;
                    stage_q <= 0;
                end else stage_q <= stage_q + 1'b1;
            end
        end
    end
endmodule
`default_nettype wire
