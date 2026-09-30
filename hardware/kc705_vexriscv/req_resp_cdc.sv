`timescale 1ns/1ps
`default_nettype none
// Single-outstanding bundled-data handshake. Each payload stays unchanged
// until the opposite domain has captured it and returned a synchronized toggle.
// Both domains must be reset together; reset cancels the outstanding transfer.
module req_resp_cdc (
    input wire s_clk, d_clk, arst,
    input wire s_req_valid, output wire s_req_ready,
    input wire s_req_write, input wire [31:0] s_req_addr, s_req_wdata,
    input wire [3:0] s_req_wstrb,
    output wire s_resp_valid, input wire s_resp_ready,
    output reg [31:0] s_resp_rdata, output reg s_resp_error,
    output wire d_req_valid, input wire d_req_ready,
    output reg d_req_write, output reg [31:0] d_req_addr, d_req_wdata,
    output reg [3:0] d_req_wstrb,
    input wire d_resp_valid, output wire d_resp_ready,
    input wire [31:0] d_resp_rdata, input wire d_resp_error
);
    (* ASYNC_REG = "TRUE" *) reg [1:0] s_reset=2'b11, d_reset=2'b11;
    always @(posedge s_clk or posedge arst)
        if (arst) s_reset <= 2'b11; else s_reset <= {s_reset[0],1'b0};
    always @(posedge d_clk or posedge arst)
        if (arst) d_reset <= 2'b11; else d_reset <= {d_reset[0],1'b0};
    wire s_rst=s_reset[1], d_rst=d_reset[1];
    reg request_toggle, response_toggle;
    (* ASYNC_REG = "TRUE" *) reg [1:0] request_sync, response_sync;
    always @(posedge d_clk or posedge arst)
        if (arst) request_sync <= 0;
        else if (d_rst) request_sync <= 0;
        else request_sync <= {request_sync[0],request_toggle};
    always @(posedge s_clk or posedge arst)
        if (arst) response_sync <= 0;
        else if (s_rst) response_sync <= 0;
        else response_sync <= {response_sync[0],response_toggle};

    reg [68:0] request_payload;
    reg [32:0] response_payload;
    localparam [1:0] IDLE=0, WAIT=1, RESPONSE=2;
    reg [1:0] s_state, d_state;
    assign s_req_ready = s_state==IDLE && !s_rst;
    assign s_resp_valid = s_state==RESPONSE && !s_rst;
    assign d_req_valid = d_state==RESPONSE && !d_rst;
    assign d_resp_ready = d_state==WAIT && !d_rst;

    always @(posedge s_clk or posedge arst) begin
        if (arst) begin s_state<=IDLE; request_toggle<=0; end
        else if (s_rst) begin s_state<=IDLE; request_toggle<=0; end
        else case (s_state)
            IDLE: if (s_req_valid) begin
                request_payload <= {s_req_write,s_req_addr,s_req_wdata,s_req_wstrb};
                request_toggle <= ~request_toggle;
                s_state <= WAIT;
            end
            WAIT: if (response_sync[1]==request_toggle) begin
                {s_resp_error,s_resp_rdata} <= response_payload;
                s_state <= RESPONSE;
            end
            RESPONSE: if (s_resp_ready) s_state <= IDLE;
            default: s_state <= IDLE;
        endcase
    end
    always @(posedge d_clk or posedge arst) begin
        if (arst) begin d_state<=IDLE; response_toggle<=0; end
        else if (d_rst) begin d_state<=IDLE; response_toggle<=0; end
        else case (d_state)
            IDLE: if (request_sync[1]!=response_toggle) begin
                {d_req_write,d_req_addr,d_req_wdata,d_req_wstrb} <= request_payload;
                d_state <= RESPONSE;
            end
            RESPONSE: if (d_req_ready) d_state <= WAIT;
            WAIT: if (d_resp_valid) begin
                response_payload <= {d_resp_error,d_resp_rdata};
                response_toggle <= request_sync[1];
                d_state <= IDLE;
            end
            default: d_state <= IDLE;
        endcase
    end
endmodule
`default_nettype wire
