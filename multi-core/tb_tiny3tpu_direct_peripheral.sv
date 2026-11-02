`timescale 1ns/1ps
module tb_tiny3tpu_direct_peripheral;
    reg clk=0,rst_n=0,req_valid=0,req_write=0,resp_ready=0;
    reg [9:0] req_addr=0;
    reg [31:0] req_wdata=0;
    reg [3:0] req_wstrb=0;
    wire req_ready,resp_valid,resp_error;
    wire [31:0] resp_rdata;
    reg [31:0] got,held;
    integer core,row,col,run;
    always #5 clk=~clk;
    tiny3tpu_direct_peripheral dut(.*);
    task access(input bit wr,input [9:0] address,input [31:0] value,
                input [3:0] strobe,input bit error,output [31:0] data);
        begin
            @(negedge clk);wait(req_ready);
            req_valid=1;req_write=wr;req_addr=address;req_wdata=value;req_wstrb=strobe;
            @(negedge clk);req_valid=0;
            // Accepted payload must be latched, independent of CPU bus changes.
            req_addr=10'h3ff;req_wdata=32'hbadbadba;req_wstrb=0;
            wait(resp_valid);#1;
            if(resp_error!==error)$fatal(1,"unexpected error %b at %h",resp_error,address);
            data=resp_rdata;
            repeat(3)begin
                @(negedge clk);
                if(!resp_valid || req_ready || resp_rdata!==data || resp_error!==error)
                    $fatal(1,"response not held under backpressure");
            end
            resp_ready=1;
            @(negedge clk);resp_ready=0;
        end
    endtask
    initial begin
        repeat(3)@(negedge clk);rst_n=1;
        access(0,10'h010,0,0,0,got);
        if(got!==32'h300)$fatal(1,"capabilities");
        access(0,10'h3ff,0,0,1,got);
        access(1,10'h200,0,15,1,got);
        for(core=0;core<8;core=core+1)for(row=0;row<4;row=row+1)begin
            access(1,10'h040+core*32+row*4,core?32'h7f7f7f7f:32'hfefefefe,15,0,got);
            access(1,10'h050+core*32+row*4,(core?32'h80:32'h1)<<(row*8),15,0,got);
        end
        // Byte enables update only the selected lane, including a no-op write.
        access(1,10'h040,32'h00030000,4'b0100,0,got);
        access(1,10'h040,32'hffffffff,0,0,got);
        for(run=1;run<=2;run=run+1)begin
            access(1,0,run==1?1:9,15,0,got);
            got=1;
            while(got&1)access(0,10'h010,0,0,0,got);
            if(!(got&2))$fatal(1,"missing completion");
            for(core=0;core<8;core=core+1)for(row=0;row<4;row=row+1)for(col=0;col<4;col=col+1)begin
                access(0,10'h200+core*64+row*16+col*4,0,0,0,got);
                if($signed(got)!==run*(core?-16256:(row==0&&col==2?3:-2)))
                    $fatal(1,"result mismatch core%0d row%0d col%0d got%0d",core,row,col,$signed(got));
            end
        end
        // Reset discards any response being held and returns to a clean port.
        @(negedge clk);req_valid=1;req_write=0;req_addr=10'h010;
        @(negedge clk);req_valid=0;
        wait(resp_valid);@(negedge clk);rst_n=0;
        repeat(2)@(negedge clk);rst_n=1;
        access(0,10'h010,0,0,0,got);
        if(got!==32'h300)$fatal(1,"reset state");
        // Abort a packed command after AXI acceptance. No stale response or
        // operand may survive reset.
        @(negedge clk);req_valid=1;req_write=1;req_addr=10'h040;
        req_wdata=32'h7f7f7f7f;req_wstrb=15;
        @(negedge clk);req_valid=0;
        wait(dut.accelerator.bvalid_reg!=0 || dut.accelerator.packed_left!=0);
        @(negedge clk);rst_n=0;
        repeat(2)@(negedge clk);rst_n=1;
        access(1,0,1,15,0,got);
        got=1;while(got&1)access(0,10'h010,0,0,0,got);
        access(0,10'h200,0,0,0,got);
        if(got!==0)$fatal(1,"partial packed write survived reset");
        $display("PASS native TPU port: signed results, continuation, strobes, errors, backpressure and reset");
        $finish;
    end
    initial begin #100000;$fatal(1,"timeout");end
endmodule
