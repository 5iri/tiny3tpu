`timescale 1ns/1ps
module tb_req_resp_cdc;
    reg s_clk=0,d_clk=0,arst=0;
    always #5 s_clk=~s_clk;
    initial begin #2.3; forever #6 d_clk=~d_clk; end
    reg s_req_valid=0,s_req_write=0,s_resp_ready=0,d_req_ready=0,d_resp_valid=0,d_resp_error=0;
    reg [31:0] s_req_addr=0,s_req_wdata=0,d_resp_rdata=0;
    reg [3:0] s_req_wstrb=0;
    wire s_req_ready,s_resp_valid,s_resp_error,d_req_valid,d_req_write,d_resp_ready;
    wire [31:0] s_resp_rdata,d_req_addr,d_req_wdata;
    wire [3:0] d_req_wstrb;
    req_resp_cdc dut(.*);
    integer count=0;
    task reset;
        begin
            #1.1 arst=1; s_req_valid=0; s_resp_ready=0; d_req_ready=0; d_resp_valid=0;
            #23.4 arst=0;
            repeat(6) @(posedge s_clk);
            if(s_resp_valid || d_req_valid) $fatal(1,"stale transfer after reset");
        end
    endtask
    task access(input [31:0] a,input [31:0] data,input [3:0] mask,input wr,input err);
        reg [31:0] expected;
        integer request_stall,response_stall,backpressure;
        begin
            expected=a^data^32'h714ab953;
            request_stall=$urandom_range(0,12);
            response_stall=$urandom_range(0,20);
            backpressure=$urandom_range(0,20);
            fork
                begin
                    @(negedge s_clk);
                    s_req_valid=1;s_req_write=wr;s_req_addr=a;s_req_wdata=data;s_req_wstrb=mask;
                    do @(posedge s_clk); while(!s_req_ready);
                    @(negedge s_clk);s_req_valid=0;
                    wait(s_resp_valid);
                    repeat(backpressure) begin
                        @(negedge s_clk);
                        if(!s_resp_valid || s_resp_rdata!==expected || s_resp_error!==err)
                            $fatal(1,"response changed under backpressure");
                    end
                    @(negedge s_clk);s_resp_ready=1;
                    @(posedge s_clk);
                    if(!s_resp_valid || s_resp_rdata!==expected || s_resp_error!==err)
                        $fatal(1,"wrong CDC response");
                    @(negedge s_clk);s_resp_ready=0;
                end
                begin
                    wait(d_req_valid);
                    repeat(request_stall) begin
                        @(negedge d_clk);
                        if(!d_req_valid || {d_req_write,d_req_addr,d_req_wdata,d_req_wstrb}!=={wr,a,data,mask})
                            $fatal(1,"request changed under backpressure");
                    end
                    @(negedge d_clk);d_req_ready=1;
                    @(posedge d_clk);
                    if(!d_req_valid || {d_req_write,d_req_addr,d_req_wdata,d_req_wstrb}!=={wr,a,data,mask})
                        $fatal(1,"wrong CDC request");
                    @(negedge d_clk);d_req_ready=0;
                    repeat(response_stall) @(negedge d_clk);
                    d_resp_valid=1;d_resp_error=err;d_resp_rdata=expected;
                    do @(posedge d_clk); while(!d_resp_ready);
                    @(negedge d_clk);d_resp_valid=0;d_resp_rdata=32'hbadfeed;
                end
            join
            count=count+1;
        end
    endtask
    initial begin
        reset();
        for(integer i=0;i<600;i=i+1) begin
            access($urandom,$urandom,i[3:0],i[0],i%7==0);
            if(i%10==0) begin
                // Cancel alternating pending requests and pending responses.
                @(negedge s_clk);s_req_valid=1;s_req_addr=$urandom;
                do @(posedge s_clk); while(!s_req_ready);
                @(negedge s_clk);s_req_valid=0;
                if(i%20==0) begin
                    wait(d_req_valid);@(negedge d_clk);d_req_ready=1;
                    @(posedge d_clk);@(negedge d_clk);d_req_ready=0;
                end
                reset();
            end
        end
        repeat(10) @(posedge s_clk);
        if(s_resp_valid || d_req_valid) $fatal(1,"duplicate transaction");
        $display("PASS CDC: %0d transfers, 60 in-flight resets, independent 100/83.333 MHz clocks",count);
        $finish;
    end
    initial begin #2000000; $fatal(1,"CDC timeout"); end
endmodule
