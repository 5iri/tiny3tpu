`timescale 1ns/1ps

module tb_tpu_core_wrapper;
    localparam int N  = 4;
    localparam int DW = 32;
    localparam int CW = 64;

    logic clk;
    logic rst;
    logic start;
    logic busy;
    logic done;

    logic load_en;
    logic load_sel;
    logic [$clog2(N)-1:0] load_row;
    logic [$clog2(N)-1:0] load_col;
    logic signed [DW-1:0] load_data;

    logic c_rd_en;
    logic [$clog2(N)-1:0] c_rd_row;
    logic [$clog2(N)-1:0] c_rd_col;
    logic signed [CW-1:0] c_rd_data;

    integer A [0:N-1][0:N-1];
    integer B [0:N-1][0:N-1];
    integer C_ref [0:N-1][0:N-1];

    integer i;
    integer j;
    integer k;
    integer errors;

    tpu_core_wrapper #(
        .N(N),
        .DW(DW),
        .CW(CW)
    ) dut (
        .clk(clk),
        .rst(rst),
        .start(start),
        .busy(busy),
        .done(done),
        .load_en(load_en),
        .load_sel(load_sel),
        .load_row(load_row),
        .load_col(load_col),
        .load_data(load_data),
        .c_rd_en(c_rd_en),
        .c_rd_row(c_rd_row),
        .c_rd_col(c_rd_col),
        .c_rd_data(c_rd_data)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        $dumpfile("tb_tpu_core_wrapper.vcd");
        $dumpvars(0, tb_tpu_core_wrapper);
    end

    initial begin
        rst = 1'b1;
        start = 1'b0;
        load_en = 1'b0;
        load_sel = 1'b0;
        load_row = '0;
        load_col = '0;
        load_data = '0;
        c_rd_en = 1'b0;
        c_rd_row = '0;
        c_rd_col = '0;
        errors = 0;

        #20;
        rst = 1'b0;

        // Build small deterministic matrices.
        for (i = 0; i < N; i++) begin
            for (j = 0; j < N; j++) begin
                A[i][j] = i + j + 1;
                B[i][j] = i + j + 5;
            end
        end

        for (i = 0; i < N; i++) begin
            for (j = 0; j < N; j++) begin
                C_ref[i][j] = 0;
                for (k = 0; k < N; k++) begin
                    C_ref[i][j] = C_ref[i][j] + A[i][k] * B[k][j];
                end
            end
        end

        // Load A scratchpad.
        load_sel = 1'b0;
        for (i = 0; i < N; i++) begin
            for (j = 0; j < N; j++) begin
                @(negedge clk);
                load_en = 1'b1;
                load_row = i[$clog2(N)-1:0];
                load_col = j[$clog2(N)-1:0];
                load_data = A[i][j];
                @(posedge clk);
            end
        end
        @(negedge clk);
        load_en = 1'b0;

        // Load B scratchpad.
        load_sel = 1'b1;
        for (i = 0; i < N; i++) begin
            for (j = 0; j < N; j++) begin
                @(negedge clk);
                load_en = 1'b1;
                load_row = i[$clog2(N)-1:0];
                load_col = j[$clog2(N)-1:0];
                load_data = B[i][j];
                @(posedge clk);
            end
        end
        @(negedge clk);
        load_en = 1'b0;

        // Run one GEMM tile.
        @(negedge clk);
        start = 1'b1;
        @(posedge clk);
        @(negedge clk);
        start = 1'b0;

        wait (done == 1'b1);
        @(posedge clk);

        // Read back C and compare.
        c_rd_en = 1'b1;
        errors = 0;
        for (i = 0; i < N; i++) begin
            for (j = 0; j < N; j++) begin
                @(negedge clk);
                c_rd_row = i[$clog2(N)-1:0];
                c_rd_col = j[$clog2(N)-1:0];
                @(posedge clk);
                #1;
                if (c_rd_data !== C_ref[i][j]) begin
                    errors = errors + 1;
                    $display("MISMATCH C[%0d][%0d] got=%0d ref=%0d",
                             i, j, c_rd_data, C_ref[i][j]);
                end
            end
        end
        c_rd_en = 1'b0;

        if (errors == 0) begin
            $display("PASSED!");
        end else begin
            $display("FAILED! mismatches=%0d", errors);
        end

        #20;
        $finish;
    end
endmodule
