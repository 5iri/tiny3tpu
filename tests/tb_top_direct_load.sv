`timescale 1ns/1ps
module tb_top_direct_load;
    parameter SMALL_N=4;
    reg clk=0, rst=1, start=0, continuing=0, we=0, sel=0, core=0, ren=0;
    reg [1:0] row=0, col=0;
    reg signed [7:0] data=0;
    wire busy,done;
    wire signed [31:0] result;
    integer ticks=0, c,r,k,pass;
    always #5 clk=~clk;
    top #(.NUM_BIG_CORES(1),.SMALL_N(SMALL_N)) dut(
        .clk(clk),.rst(rst),.ubuf_wr_en(we),.ubuf_wr_sel(sel),
        .ubuf_wr_core(core),.ubuf_wr_row(row),.ubuf_wr_col(col),.ubuf_wr_data(data),
        .start(start),.continue_accum(continuing),.busy(busy),.done(done),
        .c_rd_en(ren),.c_rd_core(core),.c_rd_row(row),.c_rd_col(col),.c_rd_data(result));
    always @(posedge clk) if (!rst && busy) ticks=ticks+1;

    task load(input integer target,bank,rr,cc,value);
        begin
            @(negedge clk); we=1;core=target;sel=bank;row=rr;col=cc;data=value;
            @(negedge clk); we=0;
        end
    endtask
    task launch(input integer retain);
        begin
            ticks=0;
            @(negedge clk);start=1;continuing=retain;
            @(negedge clk);start=0;continuing=0;
            // Changing operands while busy must not corrupt this or a later run.
            load(0,0,0,0,99);
            wait(done);@(negedge clk);
            if(ticks!=20)$fatal(1,"launch latency regressed: %0d (expected 20)",ticks);
            @(negedge clk);
        end
    endtask
    task check(input integer multiplier);
        integer cc,rr,kk,dim,want;
        begin
            ren=1;
            for(cc=0;cc<2;cc=cc+1)for(rr=0;rr<4;rr=rr+1)for(kk=0;kk<4;kk=kk+1)begin
                core=cc;row=rr;col=kk;dim=cc?SMALL_N:4;
                // A has value (core+1) and B is identity.
                want=(rr<dim&&kk<dim)?multiplier*(cc+1):0;
                #1;if(result!==want)$fatal(1,"C%0d[%0d,%0d]=%0d expected %0d",cc,rr,kk,result,want);
            end
            ren=0;
        end
    endtask
    initial begin
        repeat(3)@(negedge clk);rst=0;
        for(c=0;c<2;c=c+1)for(r=0;r<4;r=r+1)for(k=0;k<4;k=k+1)begin
            // Out-of-range small-core writes must not alias a valid address.
            load(c,0,r,k,(c&&((r>=SMALL_N)||(k>=SMALL_N)))?99:c+1);
            load(c,1,r,k,(c&&((r>=SMALL_N)||(k>=SMALL_N)))?99:(r==k));
        end
        launch(0);check(1);
        launch(1);check(2); // Reuse resident operands without reloading.
        launch(0);check(1); // Clear accumulators without erasing operands.
        @(negedge clk);rst=1;
        repeat(2)@(negedge clk);rst=0;
        launch(1);check(0); // Reset invalidates/clears data and retained sums.
        $display("PASS direct core loading: 20 cycles, resident operands, reset, busy gating, N=%0d",SMALL_N);
        $finish;
    end
    initial begin #100000;$fatal(1,"timeout");end
endmodule
