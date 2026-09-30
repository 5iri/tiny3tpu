`timescale 1ns/1ps
`default_nettype none

// Synapse32 CPU mailbox.
//
// A CPU writes HEADER and DATA, then writes SUBMIT in CONTROL.  The saved
// pair is emitted as one, two-beat AXIS command.  An AXIS response is saved
// in the same way and remains visible until the CPU writes ACK.  There is no
// speculative AXIS traffic and there is never more than one command in
// flight.
module synapse32_axis_mailbox (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        cpu_wr_en,
    input  wire        cpu_rd_en,
    input  wire [4:0]  cpu_addr,
    input  wire [31:0] cpu_wdata,
    input  wire [3:0]  cpu_wstrb,
    output reg  [31:0] cpu_rdata,

    output wire [31:0] m_axis_tdata,
    output wire [3:0]  m_axis_tkeep,
    output wire        m_axis_tvalid,
    input  wire        m_axis_tready,
    output wire        m_axis_tlast,

    input  wire [31:0] s_axis_tdata,
    input  wire [3:0]  s_axis_tkeep,
    input  wire        s_axis_tvalid,
    output wire        s_axis_tready,
    input  wire        s_axis_tlast
);
    localparam [4:0] REG_HEADER  = 5'h00;
    localparam [4:0] REG_DATA    = 5'h04;
    localparam [4:0] REG_CONTROL = 5'h08;
    localparam [4:0] REG_STATUS  = 5'h0c;
    localparam [4:0] REG_CODE    = 5'h10;
    localparam [4:0] REG_RESP    = 5'h14;

    localparam [1:0] AXI_OKAY   = 2'b00;
    localparam [1:0] AXI_SLVERR = 2'b10;
    localparam [1:0] AXI_DECERR = 2'b11;

    localparam [2:0] ST_IDLE = 3'd0;
    localparam [2:0] ST_TX0  = 3'd1;
    localparam [2:0] ST_TX1  = 3'd2;
    localparam [2:0] ST_RX0  = 3'd3;
    localparam [2:0] ST_RX1  = 3'd4;
    localparam [2:0] ST_DRAIN = 3'd5;

    reg [2:0]  state;
    reg [31:0] header_stage;
    reg [31:0] data_stage;
    reg [31:0] header_snapshot;
    reg [31:0] data_snapshot;
    reg [1:0]  response_code;
    reg [31:0] response_data;
    reg        response_ready;
    reg        misuse_error;
    reg        rx_frame_error;

    wire busy = (state != ST_IDLE);
    wire header_is_valid = (header_stage[31:16] == 16'b0) &&
                           (header_stage[11:9] == 3'b0);
    wire cpu_addr_aligned = (cpu_addr[1:0] == 2'b0);
    wire cpu_write_register = (cpu_addr == REG_HEADER) ||
                              (cpu_addr == REG_DATA) ||
                              (cpu_addr == REG_CONTROL);
    wire cpu_read_register = (cpu_addr == REG_HEADER) ||
                             (cpu_addr == REG_DATA) ||
                             (cpu_addr == REG_CONTROL) ||
                             (cpu_addr == REG_STATUS) ||
                             (cpu_addr == REG_CODE) ||
                             (cpu_addr == REG_RESP);
    wire cpu_control_write = cpu_wr_en && (cpu_addr == REG_CONTROL) &&
                              cpu_addr_aligned && cpu_wstrb == 4'hf;
    wire submit = cpu_control_write && cpu_wdata[0];
    wire ack = cpu_control_write && cpu_wdata[1];
    wire clear_misuse = cpu_control_write && cpu_wdata[2];

    function [31:0] merge_wstrb;
        input [31:0] old_value;
        input [31:0] new_value;
        input [3:0]  strobe;
        integer byte_index;
        begin
            merge_wstrb = old_value;
            for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1)
                if (strobe[byte_index])
                    merge_wstrb[(byte_index * 8) +: 8] =
                        new_value[(byte_index * 8) +: 8];
        end
    endfunction

    function [1:0] response_or_decerr;
        input [1:0] code;
        begin
            response_or_decerr = (code == AXI_OKAY || code == AXI_SLVERR ||
                                  code == AXI_DECERR) ? code : AXI_DECERR;
        end
    endfunction

    assign m_axis_tvalid = rst_n && (state == ST_TX0 || state == ST_TX1);
    assign m_axis_tdata  = (state == ST_TX0) ? header_snapshot : data_snapshot;
    assign m_axis_tkeep  = 4'hf;
    assign m_axis_tlast  = (state == ST_TX1);

    // The response side is only ready while the outstanding command is in
    // its response phase.  A normal two-beat response is consumed in RX0/RX1;
    // an early TLAST retires immediately, while an overlong response is
    // drained through TLAST so the next command cannot see its tail.
    assign s_axis_tready = rst_n && (state == ST_RX0 || state == ST_RX1 ||
                                     state == ST_DRAIN);

    always @* begin
        cpu_rdata = 32'b0;
        if (cpu_rd_en) begin
            case (cpu_addr)
                REG_HEADER:  cpu_rdata = header_stage;
                REG_DATA:    cpu_rdata = data_stage;
                REG_CONTROL: cpu_rdata = 32'b0;
                REG_STATUS:  cpu_rdata = {29'b0, misuse_error,
                                           response_ready, busy};
                REG_CODE:    cpu_rdata = {30'b0, response_code};
                REG_RESP:    cpu_rdata = response_data;
                default:     cpu_rdata = 32'b0;
            endcase
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state           <= ST_IDLE;
            header_stage    <= 32'b0;
            data_stage      <= 32'b0;
            header_snapshot <= 32'b0;
            data_snapshot   <= 32'b0;
            response_code   <= AXI_OKAY;
            response_data   <= 32'b0;
            response_ready  <= 1'b0;
            misuse_error    <= 1'b0;
            rx_frame_error  <= 1'b0;
        end else begin
            // The CPU contract is aligned LW/SW only.  In particular, CPU
            // SB/SH lane strobes are not interpreted as AXIS byte lanes.
            if (cpu_wr_en && (!cpu_addr_aligned || cpu_wstrb != 4'hf ||
                              !cpu_write_register))
                misuse_error <= 1'b1;
            if (cpu_rd_en && (!cpu_addr_aligned || !cpu_read_register))
                misuse_error <= 1'b1;

            if (cpu_wr_en && cpu_addr == REG_HEADER && cpu_addr_aligned &&
                cpu_wstrb == 4'hf)
                header_stage <= merge_wstrb(header_stage, cpu_wdata, cpu_wstrb);
            if (cpu_wr_en && cpu_addr == REG_DATA && cpu_addr_aligned &&
                cpu_wstrb == 4'hf)
                data_stage <= merge_wstrb(data_stage, cpu_wdata, cpu_wstrb);

            if (clear_misuse)
                misuse_error <= 1'b0;

            // ACK is intentionally level-triggered by the CPU write, not a
            // read side effect.  Response data/code remain readable after it.
            if (ack) begin
                if (response_ready && !busy)
                    response_ready <= 1'b0;
                else
                    misuse_error <= 1'b1;
            end

            // SUBMIT has priority over no state transition other than a
            // valid acceptance.  Staging registers remain writable in every
            // state, but a submitted snapshot is never overwritten.
            if (submit && cpu_addr_aligned && cpu_wstrb == 4'hf) begin
                if (busy || response_ready || !header_is_valid) begin
                    misuse_error <= 1'b1;
                end else begin
                    header_snapshot <= header_stage;
                    data_snapshot   <= data_stage;
                    state           <= ST_TX0;
                end
            end

            case (state)
                ST_TX0: begin
                    if (m_axis_tvalid && m_axis_tready)
                        state <= ST_TX1;
                end
                ST_TX1: begin
                    if (m_axis_tvalid && m_axis_tready)
                        state <= ST_RX0;
                end
                ST_RX0: begin
                    if (s_axis_tvalid && s_axis_tready) begin
                        if (s_axis_tlast) begin
                            // A packet ending on beat zero is complete but
                            // short.  Retire it now so it cannot deadlock.
                            response_code <= AXI_DECERR;
                            response_data <= 32'b0;
                            response_ready <= 1'b1;
                            state <= ST_IDLE;
                        end else begin
                            rx_frame_error <= (s_axis_tkeep != 4'hf) ||
                                              (s_axis_tdata[31:2] != 30'b0) ||
                                              (s_axis_tdata[1:0] == 2'b01);
                            response_code <= (s_axis_tkeep == 4'hf &&
                                              s_axis_tdata[31:2] == 30'b0) ?
                                              response_or_decerr(s_axis_tdata[1:0]) :
                                              AXI_DECERR;
                            state <= ST_RX1;
                        end
                    end
                end
                ST_RX1: begin
                    if (s_axis_tvalid && s_axis_tready) begin
                        response_data <= s_axis_tdata;
                        if (!s_axis_tlast) begin
                            // The response has more than two beats.  Keep
                            // ready asserted and drain through its TLAST.
                            response_code <= AXI_DECERR;
                            state <= ST_DRAIN;
                        end else begin
                            if (rx_frame_error || s_axis_tkeep != 4'hf)
                                response_code <= AXI_DECERR;
                            response_ready <= 1'b1;
                            state <= ST_IDLE;
                        end
                    end
                end
                ST_DRAIN: begin
                    if (s_axis_tvalid && s_axis_tready && s_axis_tlast) begin
                        response_code <= AXI_DECERR;
                        response_ready <= 1'b1;
                        state <= ST_IDLE;
                    end
                end
                default: begin
                    // ST_IDLE is deliberately passive; all work is started
                    // by the CPU SUBMIT write above.
                end
            endcase
        end
    end
endmodule

`default_nettype wire
