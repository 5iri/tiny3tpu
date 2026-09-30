`timescale 1ns/1ps
`default_nettype none

// One outstanding classic Wishbone access, 32-bit words to 64-byte bursts.
// Byte enables select the word within the burst; no read/modify/write is needed.
// The registered request isolates the controller from the CPU/CSR bus decode.
// Read selection is split 512 -> 128 -> 32 across the response register.
module litedram_wishbone32_to512 (
    input wire clk, rst,
    input wire [27:0] s_adr,
    input wire [31:0] s_dat_w,
    output wire [31:0] s_dat_r,
    input wire [3:0] s_sel,
    input wire s_cyc, s_stb, s_we,
    output wire s_ack, s_err,
    output reg [23:0] m_adr,
    output wire [511:0] m_dat_w,
    input wire [511:0] m_dat_r,
    output reg [63:0] m_sel,
    output wire m_cyc, m_stb,
    output reg m_we,
    input wire m_ack, m_err
);
    localparam [1:0] IDLE=0, BUS=1, RESPONSE=2;
    reg [1:0] state=IDLE;
    reg [31:0] write_word;
    reg [3:0] word_index;
    reg [127:0] read_quarter;
    reg error;

    assign m_dat_w = {16{write_word}};
    assign m_cyc = state == BUS;
    assign m_stb = state == BUS;
    assign s_ack = (state == RESPONSE) && !error;
    assign s_err = (state == RESPONSE) && error;
    assign s_dat_r = read_quarter[32*word_index[1:0] +: 32];

    // Payload registers need no reset: only BUS/RESPONSE expose their contents.
    always @(posedge clk) begin
        if (state == IDLE && s_cyc && s_stb) begin
            m_adr <= s_adr[27:4];
            m_we <= s_we;
            write_word <= s_dat_w;
            word_index <= s_adr[3:0];
            m_sel <= {60'b0, s_sel} << (4*s_adr[3:0]);
        end
        if (state == BUS && (m_ack || m_err)) begin
            read_quarter <= m_dat_r[128*word_index[3:2] +: 128];
            error <= m_err;
        end
        if (rst) state <= IDLE;
        else case (state)
            IDLE: if (s_cyc && s_stb) state <= BUS;
            BUS: if (m_ack || m_err) state <= RESPONSE;
            RESPONSE: state <= IDLE;
            default: state <= IDLE;
        endcase
    end
endmodule
`default_nettype wire
