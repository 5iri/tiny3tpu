`timescale 1ns/1ps
module fetch_tb;
    localparam [31:0] B=32'h80000000, IO=32'h20001000;
    reg clk=0, rst=1, ready_to_run=0;
    always #5 clk=~clk;
    reg [31:0] cpu_pc=B, cpu_rd_addr=0, cpu_wr_addr=0, cpu_wdata=0;
    reg cpu_rd_en=0, cpu_wr_en=0;
    reg [3:0] cpu_wstrb=0;
    reg [2:0] cpu_load_type=2;
    wire [31:0] cpu_instr,cpu_rdata,req_addr,req_wdata;
    wire [3:0] req_wstrb;
    wire cpu_step,fault,req_valid,req_write,resp_ready;
    reg resp_valid=0,resp_error=0;
    reg [31:0] resp_rdata=0;
    integer cycles=0, fetches=0, writes=0, reads=0, steps=0;
    integer io_fetches=0, delay_left=0, transaction=0;
    reg pending=0;
    reg [31:0] response_word=0;
    reg response_error=0;
    reg [31:0] error_addr=32'hdead0000;
    reg [31:0] mem[0:16383];
    reg expected_data=0,expected_write=0;
    reg [31:0] expected_addr,expected_word,last_load=0;
    reg [3:0] expected_strb;
    reg [31:0] last_io_instr=0;
    wire req_ready=!pending && !resp_valid && (cycles%4==3);
    wire cpu_clk;
    synapse32_clock_enable gate(.clk(clk),.enable(rst || cpu_step),.cpu_clk(cpu_clk));
    synapse32_memory_sequencer dut(.*);

    // Independent data-operation scoreboard: a repeated PC cannot suppress
    // either a read or a write. Delays are transaction-index based (seed 7).
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(rst) begin
            pending<=0; resp_valid<=0; resp_error<=0;
        end else begin
            if(resp_valid && resp_ready) resp_valid<=0;
            if(pending) begin
                if(delay_left==0) begin
                    pending<=0; resp_valid<=1;
                    resp_rdata<=response_word; resp_error<=response_error;
                end else delay_left<=delay_left-1;
            end
            if(req_valid && req_ready) begin
                if(pending || resp_valid) $fatal(1,"multiple outstanding requests");
                transaction=transaction+1;
                pending<=1; delay_left<=(transaction*7)%5;
                response_error<=req_addr==error_addr;
                response_word<=0;
                if(expected_data) begin
                    if(req_addr!==expected_addr || req_write!==expected_write ||
                       req_wdata!==expected_word || req_wstrb!==expected_strb)
                        $fatal(1,"data operation mismatch at transaction %0d",transaction);
                    expected_data=0;
                    if(req_write) begin
                        writes=writes+1;
                        if(req_addr[31:16]==16'h8000 && req_addr!=error_addr)
                            for(integer lane=0;lane<4;lane=lane+1)
                                if(req_wstrb[lane]) mem[req_addr[15:2]][lane*8+:8]<=req_wdata[lane*8+:8];
                    end else begin
                        reads=reads+1;
                        response_word<=32'h12340000+reads;
                        last_load=32'h12340000+reads;
                    end
                end else begin
                    if(req_write || req_addr!==cpu_pc || req_wdata!=0 || req_wstrb!=0)
                        $fatal(1,"unexpected/speculative fetch %h pc %h",req_addr,cpu_pc);
                    fetches=fetches+1;
                    if(req_addr[31:16]==16'h8000) response_word<=mem[req_addr[15:2]];
                    else begin
                        io_fetches=io_fetches+1;
                        last_io_instr=32'habcd0000+io_fetches;
                        response_word<=last_io_instr;
                    end
                end
            end
        end
    end
    reg held=0;
    reg [68:0] payload;
    integer last_edge=-100, cpu_edges_total=0;
    always @(posedge clk) begin
        if(rst) held<=0;
        else begin
            if(held && (!req_valid || {req_write,req_addr,req_wdata,req_wstrb}!==payload))
                $fatal(1,"request not stable through acceptance");
            held<=req_valid && !req_ready;
            payload<={req_write,req_addr,req_wdata,req_wstrb};
        end
    end
    always @(posedge cpu_clk) if(!rst) begin
        cpu_edges_total=cpu_edges_total+1;
        if(cycles-last_edge<3) $fatal(1,"lost step/settle separation");
        last_edge=cycles;
    end

    task advance(input [31:0] next_pc,input integer kind,
                 input [31:0] addr,value,input [3:0] mask);
        begin
            @(posedge cpu_clk);
            if(fault || expected_data) $fatal(1,"step before data completed");
            if(cpu_instr !== ((cpu_pc[31:16]==16'h8000) ? mem[cpu_pc[15:2]] : last_io_instr))
                $fatal(1,"stale/wrong instruction pc=%h instr=%h",cpu_pc,cpu_instr);
            if(cpu_rdata!==last_load) $fatal(1,"missing/distinct read result");
            steps=steps+1;
            #1;
            cpu_pc=next_pc; cpu_rd_en=kind==1; cpu_wr_en=kind==2;
            cpu_rd_addr=addr; cpu_wr_addr=addr; cpu_wdata=value; cpu_wstrb=mask;
            expected_data=kind!=0; expected_write=kind==2;
            expected_addr={addr[31:2],2'b0};
            expected_word=kind==2 ? value<<(addr[1:0]*8) : 0;
            expected_strb=kind==2 ? mask<<addr[1:0] : 0;
        end
    endtask
    task reset_core;
        begin
            @(negedge clk); rst=1; ready_to_run=0;
            cpu_pc=B; cpu_rd_en=0; cpu_wr_en=0; expected_data=0; last_load=0;
            repeat(3) @(negedge clk);
            rst=0;
            repeat(3) @(negedge clk);
            if(req_valid || cpu_step || fault) $fatal(1,"reset/run gating");
            ready_to_run=1;
        end
    endtask
    task check_fault;
        integer count_before;
        begin
            wait(fault); count_before=transaction;
            repeat(8) @(negedge clk);
            if(req_valid || resp_ready || cpu_step || transaction!=count_before)
                $fatal(1,"fault not quiescent");
        end
    endtask
    integer i,start_cycle,start_fetch,armed_edges;
    initial begin
        for(i=0;i<16384;i=i+1) mem[i]=32'h01000013+i*4;
        reset_core(); start_cycle=cycles; start_fetch=fetches;
        // Repeated PC, distinct stores and side-effecting loads.
        advance(B,2,IO,32'h11111111,15);
        advance(B,2,IO,32'h22222222,15);
        advance(B,1,IO,0,0);
        advance(B,1,IO,0,0);
        // Redirects, revisit, and direct-map conflict/replacement.
        advance(B+4,0,0,0,0); advance(B,0,0,0,0);
        advance(B+64,0,0,0,0); advance(B,0,0,0,0);
        for(i=0;i<12;i=i+1) advance(B,0,0,0,0);
        // Self modification of the current word, byte then halfword then word.
        advance(B,2,B+1,32'haa,1); advance(B,2,B+2,32'hbeef,3);
        advance(B,2,B,32'h87654321,15); advance(B+4,0,0,0,0);
        // Invalidate an already fetched redirect target.
        advance(B,2,B+4,32'h76543210,15); advance(B+4,0,0,0,0);
        advance(B+65532,0,0,0,0); advance(B+65532,0,0,0,0);
        advance(B+65536,0,0,0,0); advance(B+65536,0,0,0,0);
        advance(32'h20000000,0,0,0,0); advance(32'h20000000,0,0,0,0);
        advance(B,0,0,0,0); advance(B,0,0,0,0);
        if(writes!=6 || reads!=2 || io_fetches!=4) $fatal(1,"side-effect counts");
        $display("METRICS directed cycles=%0d fetches=%0d steps=%0d writes=%0d reads=%0d seed=7",
                 cycles-start_cycle,fetches-start_fetch,steps,writes,reads);
        // RAM survives reset and can be reloaded during reset; cache cannot.
        @(negedge clk); rst=1; mem[0]=32'hfeed0013;
        reset_core(); advance(B,0,0,0,0);
        // Error on an uncached boot fetch must never fill or retire.
        error_addr=B+128;
        advance(B+128,0,0,0,0); check_fault();
        error_addr=32'hdead0000; reset_core(); advance(B,1,error_addr,0,0); check_fault();
        reset_core(); advance(B,2,error_addr,32'hfff,15); check_fault();
        // Failed store to cached code, then reset/retry.
        reset_core(); advance(B,2,B,32'hffffffff,15);
        error_addr=B; check_fault();
        // Boot itself errors; verify no CPU edge escapes the error response.
        reset_core();
        check_fault();
        error_addr=32'hdead0000; reset_core(); advance(B,0,0,0,0);
        // Ready loss after the falling-edge CE sample on a reused instruction:
        // the armed edge still occurs, followed by a sticky sequencer fault.
        @(negedge clk);
        while(!cpu_step) @(negedge clk);
        #1; armed_edges=cpu_edges_total; ready_to_run=0;
        @(posedge clk); #1;
        if(!fault || cpu_step || cpu_edges_total!=armed_edges+1)
            $fatal(1,"cached-hit late-ready BUFGCE contract");
        check_fault();
        $display("PASS fetch directed: redirects/coherence/reset/backpressure/errors/repeated-PC/MMIO");
        $finish;
    end
    initial begin #200000; $fatal(1,"watchdog"); end
endmodule
