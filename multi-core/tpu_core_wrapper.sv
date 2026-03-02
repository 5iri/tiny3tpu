`timescale 1ns/1ps

module tpu_core_wrapper #(
    parameter int N  = 4,
    parameter int DW = 32,
    parameter int CW = 64
) (
    input  wire                         clk,
    input  wire                         rst,
    input  wire                         start,
    output reg                          busy,
    output reg                          done,

    input  wire                         load_en,
    input  wire                         load_sel, // 0: A_SPM, 1: B_SPM
    input  wire [$clog2(N)-1:0]         load_row,
    input  wire [$clog2(N)-1:0]         load_col,
    input  wire signed [DW-1:0]         load_data,

    input  wire                         c_rd_en,
    input  wire [$clog2(N)-1:0]         c_rd_row,
    input  wire [$clog2(N)-1:0]         c_rd_col,
    output reg signed [CW-1:0]          c_rd_data
);
    localparam  FEED_CYCLES  = (2 * N) - 1;
    localparam  FLUSH_CYCLES = (2 * N);

    localparam [2:0] ST_IDLE    = 3'd0;
    localparam [2:0] ST_CLEAR   = 3'd1;
    localparam [2:0] ST_FEED    = 3'd2;
    localparam [2:0] ST_FLUSH   = 3'd3;
    localparam [2:0] ST_CAPTURE = 3'd4;
    localparam [2:0] ST_DONE    = 3'd5;

    reg [2:0] state;

    reg clear;
    reg signed [DW-1:0] a_in [0:N-1];
    reg signed [DW-1:0] b_in [0:N-1];
    wire signed [N*DW-1:0] a_in_flat;
    wire signed [N*DW-1:0] b_in_flat;
    wire signed [N*N*CW-1:0] c_out_flat;
    wire signed [CW-1:0] c_out [0:N-1][0:N-1];

    reg signed [DW-1:0] a_spm [0:N-1][0:N-1];
    reg signed [DW-1:0] b_spm [0:N-1][0:N-1];
    reg signed [CW-1:0] c_spm [0:N-1][0:N-1];

    integer t_count;
    integer flush_count;
    integer i;
    integer j;
    integer k;

    genvar gi;
    generate
        for (gi = 0; gi < N; gi = gi + 1) begin : GEN_AB_PACK
            assign a_in_flat[(gi*DW) +: DW] = a_in[gi];
            assign b_in_flat[(gi*DW) +: DW] = b_in[gi];
        end
    endgenerate

    genvar gr;
    genvar gc;
    generate
        for (gr = 0; gr < N; gr = gr + 1) begin : GEN_C_UNPACK_ROW
            for (gc = 0; gc < N; gc = gc + 1) begin : GEN_C_UNPACK_COL
                assign c_out[gr][gc] = c_out_flat[(((gr*N)+gc)*CW) +: CW];
            end
        end
    endgenerate

    systolic_array #(
        .N(N),
        .DW(DW),
        .CW(CW)
    ) u_systolic_array (
        .clk(clk),
        .rst(rst),
        .clear(clear),
        .a_in(a_in_flat),
        .b_in(b_in_flat),
        .c_out(c_out_flat)
    );

    always @(*) begin
        c_rd_data = {CW{1'b0}};
        if (c_rd_en) begin
            c_rd_data = c_spm[c_rd_row][c_rd_col];
        end
    end

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= ST_IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            clear <= 1'b0;
            t_count <= 0;
            flush_count <= 0;

            for (i = 0; i < N; i++) begin
                a_in[i] <= {DW{1'b0}};
                b_in[i] <= {DW{1'b0}};
                for (j = 0; j < N; j++) begin
                    a_spm[i][j] <= {DW{1'b0}};
                    b_spm[i][j] <= {DW{1'b0}};
                    c_spm[i][j] <= {CW{1'b0}};
                end
            end
        end else begin
            done <= 1'b0;

            if (load_en && !busy) begin
                if (load_sel) begin
                    b_spm[load_row][load_col] <= load_data;
                end else begin
                    a_spm[load_row][load_col] <= load_data;
                end
            end

            case (state)
                ST_IDLE: begin
                    clear <= 1'b0;
                    if (start) begin
                        busy <= 1'b1;
                        t_count <= 0;
                        flush_count <= 0;
                        for (i = 0; i < N; i++) begin
                            a_in[i] <= {DW{1'b0}};
                            b_in[i] <= {DW{1'b0}};
                        end
                        state <= ST_CLEAR;
                    end
                end

                ST_CLEAR: begin
                    clear <= 1'b1;
                    for (i = 0; i < N; i++) begin
                        a_in[i] <= {DW{1'b0}};
                        b_in[i] <= {DW{1'b0}};
                    end
                    state <= ST_FEED;
                end

                ST_FEED: begin
                    clear <= 1'b0;

                    for (i = 0; i < N; i++) begin
                        k = t_count - i;
                        if ((k >= 0) && (k < N)) begin
                            a_in[i] <= a_spm[i][k];
                        end else begin
                            a_in[i] <= {DW{1'b0}};
                        end
                    end

                    for (j = 0; j < N; j++) begin
                        k = t_count - j;
                        if ((k >= 0) && (k < N)) begin
                            b_in[j] <= b_spm[k][j];
                        end else begin
                            b_in[j] <= {DW{1'b0}};
                        end
                    end

                    if (t_count == (FEED_CYCLES - 1)) begin
                        t_count <= 0;
                        flush_count <= 0;
                        state <= ST_FLUSH;
                    end else begin
                        t_count <= t_count + 1;
                    end
                end

                ST_FLUSH: begin
                    for (i = 0; i < N; i++) begin
                        a_in[i] <= {DW{1'b0}};
                        b_in[i] <= {DW{1'b0}};
                    end

                    if (flush_count == (FLUSH_CYCLES - 1)) begin
                        state <= ST_CAPTURE;
                    end else begin
                        flush_count <= flush_count + 1;
                    end
                end

                ST_CAPTURE: begin
                    for (i = 0; i < N; i++) begin
                        for (j = 0; j < N; j++) begin
                            c_spm[i][j] <= c_out[i][j];
                        end
                    end
                    busy <= 1'b0;
                    done <= 1'b1;
                    state <= ST_DONE;
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
