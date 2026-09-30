`timescale 1ns/1ps
module tb_synapse32_tpu_mmio;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0, cpu_wr_en=0, cpu_rd_en=0;
    reg [31:0] cpu_wr_addr=0, cpu_rd_addr=0, cpu_wdata=0;
    reg [3:0] cpu_wstrb=15;
    reg [2:0] cpu_load_type=2;
    reg cpu_store_fault=0, cpu_load_fault=0;
    wire write_hit, read_hit;
    wire [31:0] cpu_rdata;
    synapse32_tpu_mmio dut (.*);
    task wr(input [31:0] addr, input [31:0] data);
        begin
            @(negedge clk); cpu_wr_addr=addr; cpu_wdata=data; cpu_wr_en=1;
            @(negedge clk); cpu_wr_en=0;
        end
    endtask
    task rd_check(input [31:0] addr, input hit, input [31:0] expected);
        begin
            @(negedge clk); cpu_rd_addr=addr; cpu_rd_en=1;
            #1;
            if (read_hit!==hit || cpu_rdata!==expected)
                $fatal(1,"read %h hit=%b data=%h expected=%h",addr,read_hit,cpu_rdata,expected);
            @(negedge clk); cpu_rd_en=0;
        end
    endtask
    initial begin
        repeat(3) @(negedge clk); rst_n=1;
        wr(32'h20001000,32'hf108);
        rd_check(32'h20001000,1,32'hf108);
        // Identical low address bits must not alias the reserved window.
        wr(32'h20000000,0); wr(32'h30001000,0); wr(32'h20001020,0);
        rd_check(32'h20001000,1,32'hf108);
        rd_check(32'h30001000,0,0); rd_check(32'h20001020,0,0);
        cpu_store_fault=1; wr(32'h20001000,0); cpu_store_fault=0;
        rd_check(32'h20001000,1,32'hf108);
        cpu_load_fault=1; rd_check(32'h20001000,1,0); cpu_load_fault=0;
        cpu_load_type=0; rd_check(32'h20001000,1,0); cpu_load_type=2;
        rd_check(32'h2000100c,1,0);
        // Unsupported CPU byte store is rejected, never lane-shifted.
        cpu_wstrb=1; wr(32'h20001000,0); cpu_wstrb=15;
        rd_check(32'h20001000,1,32'hf108); rd_check(32'h2000100c,1,4);
        wr(32'h20001008,4); rd_check(32'h2000100c,1,0);
        // Faulted SUBMIT must have no effect on the peripheral.
        cpu_store_fault=1; wr(32'h20001008,1); cpu_store_fault=0;
        rd_check(32'h2000100c,1,0);
        $display("PASS synapse32_tpu_mmio: full decode, fault gating, LW/SW contract");
        $finish;
    end
    initial begin #100000; $fatal(1,"timeout"); end
endmodule
