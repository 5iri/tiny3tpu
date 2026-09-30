`timescale 1ns/1ps
module multiply_tb;
    reg clk=0, rst=1, start=0, cancel=0;
    always #5 clk=~clk;
    reg [1:0] kind=0;
    reg [31:0] a=0,b=0;
    wire busy,done;
    wire [31:0] result;
    integer checks=0,canceled=0,i,j,k,s;
    reg [31:0] corners[0:11];
    reg [31:0] rng=32'h9321c845;
    synapse32_multiply dut(.clk(clk),.rst(rst),.start(start),.cancel(cancel),
        .kind(kind),.operand_a(a),.operand_b(b),.busy(busy),.done(done),.result(result));
    function automatic [31:0] reference(input [31:0] x,y,input [1:0] op);
        reg signed [63:0] sx,sy,p;
        begin
            sx=(op==1 || op==2)?{{32{x[31]}},x}:{32'b0,x};
            sy=op==1?{{32{y[31]}},y}:{32'b0,y};
            p=sx*sy;
            reference=op==0?p[31:0]:p[63:32];
        end
    endfunction
    function automatic [31:0] random_word(input [31:0] x);
        reg [31:0] t;
        begin t=x^(x<<13);t=t^(t>>17);random_word=t^(t<<5);end
    endfunction
    task launch(input [31:0] x,y,input [1:0] op);
        begin
            @(negedge clk);a=x;b=y;kind=op;start=1;
            @(negedge clk);start=0;
            if(!busy || done) $fatal(1,"launch handshake");
        end
    endtask
    task check(input [31:0] x,y,input [1:0] op);
        reg [31:0] expected;
        integer cycle;
        begin
            expected=reference(x,y,op);
            launch(x,y,op);
            // Once launched, external operands and repeated starts must not
            // corrupt the captured operation.
            a=~x;b=~y;kind=~op;start=1;
            for(cycle=1;cycle<=4;cycle=cycle+1) begin
                @(negedge clk);
                if(cycle<4 && (!busy || done)) $fatal(1,"early completion");
            end
            if(busy || !done || result!==expected)
                $fatal(1,"MUL kind=%0d a=%h b=%h got=%h want=%h",op,x,y,result,expected);
            @(negedge clk);start=0;
            if(busy || done || result!==expected) $fatal(1,"done not one-shot or result changed");
            checks=checks+1;
        end
    endtask
    initial begin
        corners[0]=0;corners[1]=1;corners[2]=32'hffffffff;
        corners[3]=32'h80000000;corners[4]=32'h7fffffff;corners[5]=32'hffff;
        corners[6]=32'h10000;corners[7]=32'hffff0000;corners[8]=32'hfffffffe;
        corners[9]=32'h80000001;corners[10]=32'h55555555;corners[11]=32'haaaaaaaa;
        repeat(3) @(negedge clk);rst=0;
        for(k=0;k<4;k=k+1) for(i=0;i<12;i=i+1) for(j=0;j<12;j=j+1)
            check(corners[i],corners[j],k[1:0]);
        for(i=0;i<4096;i=i+1) begin
            rng=random_word(rng);a=rng;rng=random_word(rng);
            check(a,rng,i[1:0]);
        end
        for(k=0;k<4;k=k+1) for(s=0;s<=4;s=s+1) begin
            launch(32'hffff1234,32'h8000ffff,k[1:0]);
            repeat(s) @(negedge clk);
            cancel=1;start=1;
            @(negedge clk);cancel=0;start=0;
            if(busy || done) $fatal(1,"cancel lost at stage %0d",s);
            repeat(6) begin @(negedge clk);if(busy || done) $fatal(1,"stale canceled completion");end
            canceled=canceled+1;
            check(32'h89abcdef,32'hfedcba98,k[1:0]);
            launch(32'hffff1234,32'h8000ffff,k[1:0]);
            repeat(s) @(negedge clk);rst=1;start=1;
            @(negedge clk);rst=0;start=0;
            if(busy || done) $fatal(1,"reset lost at stage %0d",s);
            repeat(6) begin @(negedge clk);if(busy || done) $fatal(1,"stale reset completion");end
            check(32'hffff0001,32'h10001,k[1:0]);
        end
        // Cancel also wins an idle launch.
        @(negedge clk);start=1;cancel=1;
        @(negedge clk);start=0;cancel=0;
        if(busy || done) $fatal(1,"canceled launch admitted");
        $display("PASS multiply checks=%0d cancellations=%0d resets=%0d",checks,canceled,canceled);
        $finish;
    end
endmodule
