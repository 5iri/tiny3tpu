`timescale 1ns/1ps

module top #(
    parameter  NUM_CORES = 2,
    parameter  N         = 4,
    parameter  DW        = 32,
    parameter  CW        = 64,
    parameter  CORE_W    = (NUM_CORES <= 1) ? 1 : $clog2(NUM_CORES),
    parameter  ROW_W     = (N <= 1) ? 1 : $clog2(N)
) (
    input  wire                         clk,
    input  wire                         rst,

    // Host write port for shared UBUF model (banked by core-id).
    input  wire                         ubuf_wr_en,
    input  wire                         ubuf_wr_sel,  // 0: A bank, 1: B bank
    input  wire [CORE_W-1:0]            ubuf_wr_core,
    input  wire [ROW_W-1:0]             ubuf_wr_row,
    input  wire [ROW_W-1:0]             ubuf_wr_col,
    input  wire signed [DW-1:0]         ubuf_wr_data,

    input  wire                         start,
    output reg                          busy,
    output reg                          done,

    // Result read mux (reads C scratchpad from selected core).
    input  wire                         c_rd_en,
    input  wire [CORE_W-1:0]            c_rd_core,
    input  wire [ROW_W-1:0]             c_rd_row,
    input  wire [ROW_W-1:0]             c_rd_col,
    output reg signed [CW-1:0]          c_rd_data
);
    localparam [2:0] ST_IDLE   = 3'd0;
    localparam [2:0] ST_LOAD_A = 3'd1;
    localparam [2:0] ST_LOAD_B = 3'd2;
    localparam [2:0] ST_START  = 3'd3;
    localparam [2:0] ST_WAIT   = 3'd4;
    localparam [2:0] ST_DONE   = 3'd5;

    reg [2:0] state;

    // Shared UBUF model, banked by core-id for now.
    reg signed [DW-1:0] ubuf_a [0:NUM_CORES-1][0:N-1][0:N-1];
    reg signed [DW-1:0] ubuf_b [0:NUM_CORES-1][0:N-1][0:N-1];

    reg                       core_start     [0:NUM_CORES-1];
    reg                       core_load_en   [0:NUM_CORES-1];
    reg                       core_load_sel  [0:NUM_CORES-1];
    reg [ROW_W-1:0]           core_load_row  [0:NUM_CORES-1];
    reg [ROW_W-1:0]           core_load_col  [0:NUM_CORES-1];
    reg signed [DW-1:0]       core_load_data [0:NUM_CORES-1];

    wire                      core_busy      [0:NUM_CORES-1];
    wire                      core_done      [0:NUM_CORES-1];
    wire signed [CW-1:0]      core_c_rd_data [0:NUM_CORES-1];

    reg                       core_done_seen [0:NUM_CORES-1];

    reg [CORE_W-1:0] load_core_idx;
    reg [ROW_W-1:0]  load_row_idx;
    reg [ROW_W-1:0]  load_col_idx;

    reg all_done;
    integer i;
    integer j;
    integer k;

    generate
        genvar g;
        for (g = 0; g < NUM_CORES; g = g + 1) begin : GEN_CORES
            tpu_core_wrapper #(
                .N(N),
                .DW(DW),
                .CW(CW)
            ) u_core (
                .clk(clk),
                .rst(rst),
                .start(core_start[g]),
                .busy(core_busy[g]),
                .done(core_done[g]),
                .load_en(core_load_en[g]),
                .load_sel(core_load_sel[g]),
                .load_row(core_load_row[g]),
                .load_col(core_load_col[g]),
                .load_data(core_load_data[g]),
                .c_rd_en(c_rd_en && (c_rd_core == g)),
                .c_rd_row(c_rd_row),
                .c_rd_col(c_rd_col),
                .c_rd_data(core_c_rd_data[g])
            );
        end
    endgenerate

    always @(*) begin
        c_rd_data = {CW{1'b0}};
        if (c_rd_en) begin
            c_rd_data = core_c_rd_data[c_rd_core];
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
            load_core_idx <= {CORE_W{1'b0}};
            load_row_idx <= {ROW_W{1'b0}};
            load_col_idx <= {ROW_W{1'b0}};

            for (i = 0; i < NUM_CORES; i = i + 1) begin
                core_start[i] <= 1'b0;
                core_load_en[i] <= 1'b0;
                core_load_sel[i] <= 1'b0;
                core_load_row[i] <= {ROW_W{1'b0}};
                core_load_col[i] <= {ROW_W{1'b0}};
                core_load_data[i] <= {DW{1'b0}};
                core_done_seen[i] <= 1'b0;

                for (j = 0; j < N; j = j + 1) begin
                    for (k = 0; k < N; k = k + 1) begin
                        ubuf_a[i][j][k] <= {DW{1'b0}};
                        ubuf_b[i][j][k] <= {DW{1'b0}};
                    end
                end
            end
        end else begin
            done <= 1'b0;

            // Default pulse signals.
            for (i = 0; i < NUM_CORES; i = i + 1) begin
                core_start[i] <= 1'b0;
                core_load_en[i] <= 1'b0;
            end

            // Host can program UBUF while accelerator is idle.
            if (ubuf_wr_en && !busy) begin
                if (ubuf_wr_sel) begin
                    ubuf_b[ubuf_wr_core][ubuf_wr_row][ubuf_wr_col] <= ubuf_wr_data;
                end else begin
                    ubuf_a[ubuf_wr_core][ubuf_wr_row][ubuf_wr_col] <= ubuf_wr_data;
                end
            end

            case (state)
                ST_IDLE: begin
                    if (start) begin
                        busy <= 1'b1;
                        load_core_idx <= {CORE_W{1'b0}};
                        load_row_idx <= {ROW_W{1'b0}};
                        load_col_idx <= {ROW_W{1'b0}};
                        for (i = 0; i < NUM_CORES; i = i + 1) begin
                            core_done_seen[i] <= 1'b0;
                        end
                        state <= ST_LOAD_A;
                    end
                end

                ST_LOAD_A: begin
                    core_load_en[load_core_idx] <= 1'b1;
                    core_load_sel[load_core_idx] <= 1'b0;
                    core_load_row[load_core_idx] <= load_row_idx;
                    core_load_col[load_core_idx] <= load_col_idx;
                    core_load_data[load_core_idx] <= ubuf_a[load_core_idx][load_row_idx][load_col_idx];

                    if (load_col_idx == N-1) begin
                        load_col_idx <= {ROW_W{1'b0}};
                        if (load_row_idx == N-1) begin
                            load_row_idx <= {ROW_W{1'b0}};
                            if (load_core_idx == NUM_CORES-1) begin
                                load_core_idx <= {CORE_W{1'b0}};
                                state <= ST_LOAD_B;
                            end else begin
                                load_core_idx <= load_core_idx + 1'b1;
                            end
                        end else begin
                            load_row_idx <= load_row_idx + 1'b1;
                        end
                    end else begin
                        load_col_idx <= load_col_idx + 1'b1;
                    end
                end

                ST_LOAD_B: begin
                    core_load_en[load_core_idx] <= 1'b1;
                    core_load_sel[load_core_idx] <= 1'b1;
                    core_load_row[load_core_idx] <= load_row_idx;
                    core_load_col[load_core_idx] <= load_col_idx;
                    core_load_data[load_core_idx] <= ubuf_b[load_core_idx][load_row_idx][load_col_idx];

                    if (load_col_idx == N-1) begin
                        load_col_idx <= {ROW_W{1'b0}};
                        if (load_row_idx == N-1) begin
                            load_row_idx <= {ROW_W{1'b0}};
                            if (load_core_idx == NUM_CORES-1) begin
                                load_core_idx <= {CORE_W{1'b0}};
                                state <= ST_START;
                            end else begin
                                load_core_idx <= load_core_idx + 1'b1;
                            end
                        end else begin
                            load_row_idx <= load_row_idx + 1'b1;
                        end
                    end else begin
                        load_col_idx <= load_col_idx + 1'b1;
                    end
                end

                ST_START: begin
                    for (i = 0; i < NUM_CORES; i = i + 1) begin
                        core_start[i] <= 1'b1;
                    end
                    state <= ST_WAIT;
                end

                ST_WAIT: begin
                    for (i = 0; i < NUM_CORES; i = i + 1) begin
                        if (core_done[i]) begin
                            core_done_seen[i] <= 1'b1;
                        end
                    end

                    if (all_done) begin
                        busy <= 1'b0;
                        done <= 1'b1;
                        state <= ST_DONE;
                    end
                end

                ST_DONE: begin
                    state <= ST_IDLE;
                end

                default: begin
                    state <= ST_IDLE;
                end
            endcase
        end
    end
endmodule
