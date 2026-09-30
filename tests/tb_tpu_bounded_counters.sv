`timescale 1ns/1ps
module counter_case #(parameter N=4)(input wire clk,output reg finished=0);
    reg rst=1,start=0,load_en=0,load_sel=0,c_rd_en=0;
    reg [$clog2(N)-1:0] load_row=0,load_col=0,c_rd_row=0,c_rd_col=0;
    reg signed [7:0] load_data=0;
    wire busy,done,old_busy,old_done;
    wire signed [31:0] c_rd_data,old_data;
    tpu_core_wrapper #(.N(N)) dut(.*);
    tpu_core_wrapper_integer_counters #(.N(N)) original(
        .clk(clk),.rst(rst),.start(start),.load_en(load_en),.load_sel(load_sel),
        .load_row(load_row),.load_col(load_col),.load_data(load_data),
        .c_rd_en(c_rd_en),.c_rd_row(c_rd_row),.c_rd_col(c_rd_col),
        .busy(old_busy),.done(old_done),.c_rd_data(old_data));
    reg [31:0] rng=32'h7293bf16+N;
    integer completions=0,checks=0;
    task compare;
        begin
            if ({busy,done,c_rd_data} !== {old_busy,old_done,old_data} ||
                dut.a_in_flat !== original.a_in_flat || dut.b_in_flat !== original.b_in_flat ||
                dut.c_out_flat !== original.c_out_flat || dut.state !== original.state ||
                dut.t_count !== original.t_count || dut.flush_count !== original.flush_count)
                $fatal(1,"bounded counter mismatch N=%0d at check %0d",N,checks);
            if(done) completions=completions+1;
            checks=checks+1;
        end
    endtask
    integer i;
    initial begin
        repeat(3) @(negedge clk);
        rst=0;
        // Load every signed operand position before the first computation.
        for(i=0;i<2*N*N;i=i+1) begin
            load_en=1;load_sel=i/(N*N);load_row=(i/N)%N;load_col=i%N;load_data=8'h81+i*13;
            @(negedge clk);compare();
        end
        load_en=0;start=1;
        @(negedge clk);compare();start=0;
        repeat(4*N+8) begin @(negedge clk);compare();end
        for(i=0;i<16000;i=i+1) begin
            rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
            start=(i%59)==0;
            load_en=rng[0];load_sel=rng[1];load_data=rng[15:8];
            load_row=rng[18:16]%N;load_col=rng[22:20]%N;
            c_rd_en=rng[2];c_rd_row=rng[26:24]%N;c_rd_col=rng[30:28]%N;
            // Include reset pulses entirely between clock edges.
            if((i%521)==520) begin #1 rst=1;#2 rst=0;end
            @(negedge clk);compare();
        end
        if(completions<100) $fatal(1,"insufficient completed matrices");
        $display("PASS bounded TPU counters N=%0d: %0d cycle comparisons, %0d completions",N,checks,completions);
        finished=1;
    end
endmodule
module tb_tpu_bounded_counters;
    reg clk=0;always #5 clk=~clk;
    wire [2:0] finished;
    counter_case #(.N(2)) c2(clk,finished[0]);
    counter_case #(.N(4)) c4(clk,finished[1]);
    counter_case #(.N(8)) c8(clk,finished[2]);
    initial begin wait(&finished);$display("PASS all bounded counter regressions");$finish;end
    initial begin #1000000;$fatal(1,"timeout");end
endmodule
