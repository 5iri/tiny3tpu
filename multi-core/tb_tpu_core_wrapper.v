`timescale 1ns/1ps

module tb_tpu_core_wrapper #(parameter int N = 8);
    localparam int DW = 8;
    localparam int CW = 32;

    logic clk;
    logic rst;
    logic start;
    logic continue_accum;
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

    task automatic launch(input logic continuation);
        begin
            @(negedge clk);
            continue_accum = continuation;
            start = 1'b1;
            @(negedge clk);
            start = 1'b0;
            continue_accum = 1'b0;
            wait (done == 1'b1);
            @(posedge clk);
            #1;
        end
    endtask

    task automatic launch_with_busy_modifier;
        begin
            @(negedge clk);
            continue_accum = 1'b0;
            start = 1'b1;
            @(negedge clk);
            start = 1'b0;
            // A second START carrying the modifier while busy is ignored and
            // must not change the accepted clear-first command.
            continue_accum = 1'b1;
            start = 1'b1;
            @(negedge clk);
            start = 1'b0;
            continue_accum = 1'b0;
            wait (done == 1'b1);
            @(posedge clk);
            #1;
        end
    endtask

    task automatic check_result(input integer scale, input [255:0] label);
        begin
            errors = 0;
            c_rd_en = 1'b1;
            for (i = 0; i < N; i++) begin
                for (j = 0; j < N; j++) begin
                    @(negedge clk);
                    c_rd_row = i[$clog2(N)-1:0];
                    c_rd_col = j[$clog2(N)-1:0];
                    @(posedge clk);
                    #1;
                    if (c_rd_data !== C_ref[i][j] * scale) begin
                        errors = errors + 1;
                        $display("%0s mismatch C[%0d][%0d] got=%0d ref=%0d",
                                 label, i, j, c_rd_data, C_ref[i][j] * scale);
                    end
                end
            end
            c_rd_en = 1'b0;
            if (errors != 0) $fatal(1, "%0s had %0d mismatches", label, errors);
        end
    endtask

    tpu_core_wrapper #(
        .N(N),
        .DW(DW),
        .CW(CW)
    ) dut (
        .clk(clk),
        .rst(rst),
        .start(start),
        .continue_accum(continue_accum),
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
        continue_accum = 1'b0;
        load_en = 1'b0;
        load_sel = 1'b0;
        load_row = {($clog2(N)){1'b0}};
        load_col = {($clog2(N)){1'b0}};
        load_data = {DW{1'b0}};
        c_rd_en = 1'b0;
        c_rd_row = {($clog2(N)){1'b0}};
        c_rd_col = {($clog2(N)){1'b0}};
        errors = 0;

        #20;
        rst = 1'b0;

        // Build small deterministic matrices.
        for (i = 0; i < N; i++) begin
            for (j = 0; j < N; j++) begin
                A[i][j] = ((i+j)%4 == 0) ? -3 : i + j + 1;
                B[i][j] = ((i+2*j)%3 == 0) ? -2 : i + j + 5;
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

        // Three K tiles: clear once, then preserve through two more STARTs.
        launch_with_busy_modifier();
        check_result(1, "first clear tile");
        launch(1'b1);
        launch(1'b1);
        check_result(3, "three-tile accumulation");

        // A legacy START after continuation must clear the prior sum.
        launch(1'b0);
        check_result(1, "ordinary START clears carried sum");

        // Reset discards the partial sum and scratchpads; reload and verify a
        // fresh default START still produces exactly one matrix product.
        @(negedge clk); rst = 1'b1;
        repeat (2) @(negedge clk);
        rst = 1'b0;
        for (i = 0; i < N; i++) begin
            for (j = 0; j < N; j++) begin
                @(negedge clk);
                load_en = 1'b1;
                load_sel = 1'b0;
                load_row = i[$clog2(N)-1:0];
                load_col = j[$clog2(N)-1:0];
                load_data = A[i][j];
                @(posedge clk);
            end
        end
        for (i = 0; i < N; i++) begin
            for (j = 0; j < N; j++) begin
                @(negedge clk);
                load_en = 1'b1;
                load_sel = 1'b1;
                load_row = i[$clog2(N)-1:0];
                load_col = j[$clog2(N)-1:0];
                load_data = B[i][j];
                @(posedge clk);
            end
        end
        @(negedge clk); load_en = 1'b0;
        launch(1'b0);
        check_result(1, "reset clears accumulator");

        $display("PASS PE accumulation N=%0d", N);
        #20;
        $finish;
    end
endmodule
