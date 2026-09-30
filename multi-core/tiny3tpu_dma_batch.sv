`timescale 1ns/1ps
`default_nettype none
// A DMA descriptor carries N two-word commands and N two-word responses.
// Split outgoing TLAST at each command; join response packets into one frame.
// There is no buffering here: both directions preserve ready/valid stalls.
module tiny3tpu_dma_batch (
    input wire clk, input wire rst, input wire start,
    input wire [15:0] word_count,
    output reg protocol_error, output reg command_error,
    input wire [31:0] s_tx_data, input wire [3:0] s_tx_keep,
    input wire s_tx_last, input wire s_tx_valid, output wire s_tx_ready,
    output wire [31:0] m_cmd_data, output wire [3:0] m_cmd_keep,
    output wire m_cmd_last, output wire m_cmd_valid, input wire m_cmd_ready,
    input wire [31:0] s_resp_data, input wire [3:0] s_resp_keep,
    input wire s_resp_last, input wire s_resp_valid, output wire s_resp_ready,
    output wire [31:0] m_rx_data, output wire [3:0] m_rx_keep,
    output wire m_rx_last, output wire m_rx_valid, input wire m_rx_ready
);
    reg [15:0] tx_left, rx_left;
    assign m_cmd_data=s_tx_data;
    assign m_cmd_keep=s_tx_keep;
    assign m_cmd_last=tx_left[0];
    assign m_cmd_valid=!rst && tx_left!=0 && s_tx_valid;
    assign s_tx_ready=!rst && tx_left!=0 && m_cmd_ready;
    assign m_rx_data=s_resp_data;
    assign m_rx_keep=s_resp_keep;
    assign m_rx_last=rx_left==1;
    assign m_rx_valid=!rst && rx_left!=0 && s_resp_valid;
    assign s_resp_ready=!rst && rx_left!=0 && m_rx_ready;
    always @(posedge clk) begin
        if (rst) begin
            tx_left<=0; rx_left<=0; protocol_error<=0; command_error<=0;
        end else if (start) begin
            tx_left<=word_count; rx_left<=word_count;
            protocol_error<=word_count==0 || word_count[0]; command_error<=0;
        end else begin
            if (s_tx_valid && s_tx_ready) begin
                tx_left<=tx_left-1'b1;
                if (s_tx_keep!=4'hf || s_tx_last!=(tx_left==1)) protocol_error<=1;
            end
            if (s_resp_valid && s_resp_ready) begin
                rx_left<=rx_left-1'b1;
                if (s_resp_keep!=4'hf || s_resp_last!=rx_left[0]) protocol_error<=1;
                if (!rx_left[0] && s_resp_data!=0) command_error<=1;
            end
        end
    end
endmodule
`default_nettype wire
