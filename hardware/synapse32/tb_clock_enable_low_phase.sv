`timescale 1ns/1ps
module tb_clock_enable_low_phase;
    reg clk = 0, enable = 0;
    wire cpu_clk;
    synapse32_clock_enable dut(.clk(clk), .enable(enable), .cpu_clk(cpu_clk));
    task check(input expected);
        #0.1;
        if (cpu_clk !== expected) $fatal(1, "clock gate mismatch at %0t: got %b expected %b", $time, cpu_clk, expected);
    endtask
    initial begin
        #2; clk = 1; check(0);
        #2; clk = 0;
        #1; enable = 1; // Arrives after falling edge, before next rising edge.
        #1; clk = 1; check(1);
        #1; enable = 0; check(1); // Never truncate an active high pulse.
        #1; clk = 0; check(0);
        #2; clk = 1; check(0);
        #1; enable = 1; check(0); // Never start a pulse halfway through high.
        #1; clk = 0;
        #1; enable = 0; // Disable late in low phase; next pulse must be suppressed.
        #1; clk = 1; check(0);
        #1; clk = 0;
        #1; enable = 1;
        #1; clk = 1; check(1);
        #1; clk = 0; check(0);
        #1; clk = 1; check(1);
        #1; clk = 0; check(0);
        $display("PASS BUFGCE low-phase enable and complete-pulse behavior");
        $finish;
    end
endmodule
