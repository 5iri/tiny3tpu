module pe #(
    parameter integer DW = 8,
    parameter integer CW = 32
) (
    input wire clk,
    input wire rst,
    input wire clear,
    input wire signed [DW-1:0] a_in,
    input wire signed [DW-1:0] b_in,
    output reg signed [DW-1:0] a_out,
    output reg signed [DW-1:0] b_out,
    output wire signed [CW-1:0] c
);
    // DSP48 accumulator registers have synchronous reset only. Keep the payload
    // reset-free and mask it with asynchronously reset ownership. First MAC after
    // reset starts from zero; clear retains the original one-cycle behavior.
    reg signed [CW-1:0] c_payload;
    reg c_valid;
    wire signed [CW-1:0] feedback = c_valid ? c_payload : {CW{1'b0}};
    assign c = feedback;
    always @(posedge clk or posedge rst) begin
        if (rst) c_valid <= 1'b0;
        else c_valid <= 1'b1;
    end
    always @(posedge clk) begin
        if (clear) c_payload <= 0;
        else c_payload <= feedback + (a_in * b_in);
    end
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            a_out <= 0;
            b_out <= 0;
        end 
        else if (clear) begin
            a_out <= a_in;
            b_out <= b_in;
        end 
        else begin
            a_out <= a_in;
            b_out <= b_in;
        end
    end
endmodule
