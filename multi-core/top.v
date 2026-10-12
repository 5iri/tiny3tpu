`timescale 1ns/1ps

module top #(
    // Default board contract: two 4x4 cores with a shared host operand aperture.
    // Larger heterogeneous arrays remain available through parameter overrides.
    parameter  NUM_CORES       = 2,
    parameter  N               = 4,
    parameter  DW              = 8,
    parameter  CW              = 32,
    parameter  NUM_BIG_CORES   = 2,
    parameter  SMALL_N         = 4,
    parameter  NUM_SMALL_CORES = NUM_CORES - NUM_BIG_CORES,
    parameter  BIG_N           = N,
    parameter  N_MAX           = (BIG_N >= SMALL_N) ? BIG_N : SMALL_N,
    parameter  CORE_W          = (NUM_CORES <= 1) ? 1 : $clog2(NUM_CORES),
    parameter  ROW_W           = (N_MAX <= 1) ? 1 : $clog2(N_MAX),
    parameter  BIG_ROW_W       = (BIG_N <= 1) ? 1 : $clog2(BIG_N),
    parameter  SMALL_ROW_W     = (SMALL_N <= 1) ? 1 : $clog2(SMALL_N)
) (
    input  wire                         clk,
    input  wire                         rst,

    // Host operand aperture. Writes go directly to the selected core scratchpad.
    input  wire                         ubuf_wr_en,
    input  wire                         ubuf_wr_sel,  // 0: A bank, 1: B bank
    input  wire [CORE_W-1:0]            ubuf_wr_core,
    input  wire [ROW_W-1:0]             ubuf_wr_row,
    input  wire [ROW_W-1:0]             ubuf_wr_col,
    input  wire signed [DW-1:0]         ubuf_wr_data,

    input  wire                         start,
    input  wire                         continue_accum,
    output reg                          busy,
    output reg                          done,

    // Result read mux (reads C scratchpad from selected core).
    input  wire                         c_rd_en,
    input  wire [CORE_W-1:0]            c_rd_core,
    input  wire [ROW_W-1:0]             c_rd_row,
    input  wire [ROW_W-1:0]             c_rd_col,
    output reg signed [CW-1:0]          c_rd_data
);
    // The core scratchpads own operands. The previous duplicate UBUF required
    // 2*NUM_CORES*N*N byte-copy cycles on every launch, even for resident rows.
    localparam [2:0] ST_IDLE=3'd0, ST_START=3'd3, ST_WAIT=3'd4, ST_DONE=3'd5;
    reg [2:0] state;
    reg core_start [0:NUM_CORES-1];
    reg core_continue [0:NUM_CORES-1];
    wire core_busy [0:NUM_CORES-1];
    wire core_done [0:NUM_CORES-1];
    wire signed [CW-1:0] core_c_rd_data [0:NUM_CORES-1];
    reg core_done_seen [0:NUM_CORES-1];
    reg run_continue;
    reg all_done;
    integer i;

    generate
        genvar g_big;
        for (g_big = 0; g_big < NUM_BIG_CORES; g_big = g_big + 1) begin : GEN_BIG_CORES
            tpu_core_wrapper #(
                .N(BIG_N),
                .DW(DW),
                .CW(CW)
            ) u_core (
                .clk(clk),
                .rst(rst),
                .start(core_start[g_big]),
                .continue_accum(core_continue[g_big]),
                .busy(core_busy[g_big]),
                .done(core_done[g_big]),
                .load_en(ubuf_wr_en && !busy && ubuf_wr_core == g_big &&
                         ubuf_wr_row < BIG_N && ubuf_wr_col < BIG_N),
                .load_sel(ubuf_wr_sel),
                .load_row(ubuf_wr_row[BIG_ROW_W-1:0]),
                .load_col(ubuf_wr_col[BIG_ROW_W-1:0]),
                .load_data(ubuf_wr_data),
                .c_rd_en(c_rd_en && (c_rd_core == g_big) &&
                         (c_rd_row < BIG_N) && (c_rd_col < BIG_N)),
                .c_rd_row(c_rd_row[BIG_ROW_W-1:0]),
                .c_rd_col(c_rd_col[BIG_ROW_W-1:0]),
                .c_rd_data(core_c_rd_data[g_big])
            );
        end

        genvar g_small;
        for (g_small = 0; g_small < NUM_SMALL_CORES; g_small = g_small + 1) begin : GEN_SMALL_CORES
            localparam integer CORE_IDX = NUM_BIG_CORES + g_small;
            tpu_core_wrapper #(
                .N(SMALL_N),
                .DW(DW),
                .CW(CW)
            ) u_core (
                .clk(clk),
                .rst(rst),
                .start(core_start[CORE_IDX]),
                .continue_accum(core_continue[CORE_IDX]),
                .busy(core_busy[CORE_IDX]),
                .done(core_done[CORE_IDX]),
                .load_en(ubuf_wr_en && !busy && ubuf_wr_core == CORE_IDX &&
                         ubuf_wr_row < SMALL_N && ubuf_wr_col < SMALL_N),
                .load_sel(ubuf_wr_sel),
                .load_row(ubuf_wr_row[SMALL_ROW_W-1:0]),
                .load_col(ubuf_wr_col[SMALL_ROW_W-1:0]),
                .load_data(ubuf_wr_data),
                .c_rd_en(c_rd_en && (c_rd_core == CORE_IDX) &&
                         (c_rd_row < SMALL_N) && (c_rd_col < SMALL_N)),
                .c_rd_row(c_rd_row[SMALL_ROW_W-1:0]),
                .c_rd_col(c_rd_col[SMALL_ROW_W-1:0]),
                .c_rd_data(core_c_rd_data[CORE_IDX])
            );
        end
    endgenerate

    always @(*) begin
        c_rd_data = {CW{1'b0}};
        if (c_rd_en && (c_rd_core < NUM_CORES)) begin
            if ((c_rd_core >= NUM_BIG_CORES) &&
                ((c_rd_row >= SMALL_N) || (c_rd_col >= SMALL_N))) begin
                c_rd_data = {CW{1'b0}};
            end else begin
                c_rd_data = core_c_rd_data[c_rd_core];
            end
        end

        all_done = 1'b1;
        for (i = 0; i < NUM_CORES; i = i + 1) begin
            if (!(core_done_seen[i] || core_done[i])) begin
                all_done = 1'b0;
            end
        end
    end

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= ST_IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            run_continue <= 1'b0;
            for (i=0; i<NUM_CORES; i=i+1) begin
                core_start[i] <= 1'b0;
                core_continue[i] <= 1'b0;
                core_done_seen[i] <= 1'b0;
            end
        end else begin
            done <= 1'b0;
            for (i=0; i<NUM_CORES; i=i+1) begin
                core_start[i] <= 1'b0;
                core_continue[i] <= 1'b0;
            end
            case (state)
                ST_IDLE: if (start) begin
                    busy <= 1'b1;
                    run_continue <= continue_accum;
                    for (i=0; i<NUM_CORES; i=i+1) core_done_seen[i] <= 1'b0;
                    state <= ST_START;
                end
                ST_START: begin
                    for (i=0; i<NUM_CORES; i=i+1) begin
                        core_start[i] <= 1'b1;
                        core_continue[i] <= run_continue;
                    end
                    state <= ST_WAIT;
                end
                ST_WAIT: begin
                    for (i=0; i<NUM_CORES; i=i+1)
                        if (core_done[i]) core_done_seen[i] <= 1'b1;
                    if (all_done) begin
                        busy <= 1'b0;
                        done <= 1'b1;
                        state <= ST_DONE;
                    end
                end
                ST_DONE: state <= ST_IDLE;
                default: state <= ST_IDLE;
            endcase
        end
    end
endmodule
