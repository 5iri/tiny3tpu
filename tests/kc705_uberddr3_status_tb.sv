`timescale 1ns/1ps
module kc705_uberddr3_status_tb;
    reg clk = 0, rst_n = 0, done = 0;
    reg [31:0] debug = 0;
    wire passed, failed;
    always #5 clk = !clk;
    kc705_uberddr3_status #(.TIMER_BITS(5)) dut (.*);
    task tick;
        begin @(posedge clk); #1; end
    endtask
    task reset;
        begin
            @(negedge clk); rst_n = 0; debug = 0; done = 0;
            tick();
            if (passed || failed) $fatal(1, "reset did not clear status");
            @(negedge clk); rst_n = 1;
        end
    endtask
    initial begin
        reset();
        done = 1;
        tick();
        if (passed) $fatal(1, "completion without verified reads passed");
        debug[30] = 1;
        tick();
        if (!passed || failed) $fatal(1, "clean BIST did not pass");
        repeat (40) tick();
        if (!passed || failed) $fatal(1, "watchdog ran after success");

        debug[31] = 1;
        tick();
        if (passed || !failed) $fatal(1, "late failure did not override pass");
        debug[31] = 0;
        repeat (4) tick();
        if (passed || !failed) $fatal(1, "retry concealed a failure");

        reset();
        done = 1; debug = 32'hc0000000;
        tick();
        if (passed || !failed) $fatal(1, "error lost to simultaneous completion");

        reset();
        repeat (18) tick();
        if (passed || !failed) $fatal(1, "stuck calibration did not time out");
        done = 1; debug[30] = 1;
        tick();
        if (passed || !failed) $fatal(1, "late completion concealed timeout");

        reset();
        done = 1; debug[30] = 1;
        tick();
        if (!passed || failed) $fatal(1, "new test failed after external reset");
        $display("PASS: clean completion, missing reads, sticky error, retry, simultaneous error, timeout, reset");
        $finish;
    end
    initial begin #10000; $fatal(1, "testbench timeout"); end
endmodule
