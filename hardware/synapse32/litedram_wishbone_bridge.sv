`timescale 1ns/1ps
`default_nettype none

// Single-outstanding native request/response to 32-bit classic Wishbone.
// Addresses are byte addresses; base decoding/subtraction belongs to the caller.
// Reset is synchronous and must be coordinated with the Wishbone slave.
module litedram_wishbone_bridge (
    input  wire        clk,
    input  wire        rst,
    input  wire        req_valid,
    output wire        req_ready,
    input  wire        req_write,
    input  wire [31:0] req_addr,
    input  wire [31:0] req_wdata,
    input  wire [3:0]  req_wstrb,
    output wire        resp_valid,
    input  wire        resp_ready,
    output reg  [31:0] resp_rdata,
    output reg         resp_error,
    output reg  [29:0] wb_adr,
    output reg  [31:0] wb_dat_w,
    output reg  [3:0]  wb_sel,
    output wire        wb_cyc,
    output wire        wb_stb,
    output reg         wb_we,
    input  wire        wb_ack,
    input  wire        wb_err,
    input  wire [31:0] wb_dat_r
);
    localparam [1:0] IDLE = 2'd0, BUS = 2'd1, RESPONSE = 2'd2;
    reg [1:0] state;

    assign req_ready = (state == IDLE) && !rst;
    assign wb_cyc = (state == BUS);
    assign wb_stb = (state == BUS);
    assign resp_valid = (state == RESPONSE);

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            wb_adr <= 0;
            wb_dat_w <= 0;
            wb_sel <= 0;
            wb_we <= 0;
            resp_rdata <= 0;
            resp_error <= 0;
        end else begin
            case (state)
                IDLE: if (req_valid && req_ready) begin
                    wb_adr <= req_addr[31:2];
                    wb_dat_w <= req_wdata;
                    wb_sel <= req_wstrb;
                    wb_we <= req_write;
                    state <= BUS;
                end
                BUS: if (wb_ack || wb_err) begin
                    resp_rdata <= wb_dat_r;
                    // ERR wins when ACK and ERR are asserted together.
                    resp_error <= wb_err;
                    state <= RESPONSE;
                end
                RESPONSE: if (resp_ready) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
