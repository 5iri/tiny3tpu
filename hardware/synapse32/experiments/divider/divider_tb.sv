`timescale 1ns/1ps
module divider_tb;
    reg clk=0,rst=1,start=0,cancel=0,signed_mode=0,remainder_mode=0;
    reg [31:0] dividend=0,divisor=0;
    wire busy,done;
    wire [31:0] result;
    integer i,op,cycles,checks=0;
    reg [31:0] rng=32'hbd1057ab,a,b,want;
    reg signed [63:0] sa,sb,tmp;
    divider dut(.*);
    always #5 clk=~clk;
    task run(input [31:0] x,y,input integer mode);
        begin
            sa={{32{x[31]}},x}; sb={{32{y[31]}},y};
            if(y==0) want=mode[1]?x:32'hffffffff;
            else begin
                case(mode)
                    0: tmp=sa/sb;
                    1: tmp={32'b0,x}/{32'b0,y};
                    2: tmp=sa%sb;
                    3: tmp={32'b0,x}%{32'b0,y};
                endcase
                want=tmp[31:0];
            end
            @(negedge clk);
            dividend=x; divisor=y; signed_mode=!mode[0]; remainder_mode=mode[1]; start=1;
            @(negedge clk); start=0; cycles=0;
            // Deliberately destroy live operands/modes after launch.
            dividend=~x; divisor=~y; signed_mode=mode[0]; remainder_mode=!mode[1];
            while(!done) begin
                if(!busy || cycles>=32) $fatal(1,"bad busy/latency");
                @(negedge clk); cycles=cycles+1;
            end
            if(result!==want) $fatal(1,"op=%0d a=%h b=%h result=%h expected=%h",mode,x,y,result,want);
            if(busy) $fatal(1,"done and busy overlap");
            if(cycles!=((y==0 || (!mode[0] && x==32'h80000000 && y==32'hffffffff))?0:32))
                $fatal(1,"unexpected latency %0d",cycles);
            @(negedge clk);
            if(done || busy) $fatal(1,"completion not one-shot");
            if(result!==want) $fatal(1,"result not held");
            checks=checks+1;
        end
    endtask
    initial begin
        repeat(3) @(negedge clk); rst=0;
        for(op=0;op<4;op=op+1) begin
            run(32'h80000000,32'hffffffff,op);
            run(32'h80000000,0,op);
            run(0,0,op);
            run(32'hffffffff,0,op);
            run(32'h80000000,32'h80000000,op);
        end
        for(i=0;i<4096;i=i+1) begin
            rng=rng^(rng<<13); rng=rng^(rng>>17); rng=rng^(rng<<5); a=rng;
            rng=rng^(rng<<13); rng=rng^(rng>>17); rng=rng^(rng<<5); b=rng;
            for(op=0;op<4;op=op+1) run(a,b,op);
        end
        // Cancel at every iteration boundary, including last iteration.
        for(i=0;i<33;i=i+1) begin
            @(negedge clk); dividend=32'h87654321; divisor=3; start=1;
            @(negedge clk); start=0;
            repeat(i) @(negedge clk);
            cancel=1; @(negedge clk); cancel=0;
            if(busy || done) $fatal(1,"cancel failed boundary %0d",i);
            repeat(34) begin
                @(negedge clk);
                if(busy || done) $fatal(1,"canceled operation reappeared");
            end
            run(101,7,i%4);
        end
        $display("PASS divider arithmetic=%0d cancel-boundaries=33 captured-inputs exact-latency",checks);
        $finish;
    end
endmodule
