module tb;
reg clk=0,rst=1,clear=0; reg signed [7:0] a=0,b=0;
wire signed [7:0] ga,gb,ma,mb;wire signed [31:0] gc,mc;
gold g(.clk(clk),.rst(rst),.clear(clear),.a_in(a),.b_in(b),.a_out(ga),.b_out(gb),.c(gc));
pe_mapped m(.clk(clk),.rst(rst),.clear(clear),.a_in(a),.b_in(b),.a_out(ma),.b_out(mb),.c(mc));
always #5 clk=~clk;
integer i,seed=32'h41327355,checks=0;
task check;
begin
 if ({ga,gb,gc} !== {ma,mb,mc}) begin
  $display("FAIL i=%0d rst=%b clear=%b a=%0d b=%0d gold=%h mapped=%h",i,rst,clear,a,b,{ga,gb,gc},{ma,mb,mc});$fatal;
 end
 checks=checks+1;
end
endtask
initial begin
 repeat(2) @(negedge clk);rst=0;
 for(i=0;i<4096;i=i+1) begin
  @(negedge clk);a=$random(seed);b=$random(seed);clear=(i%29==0);
  if(i%101==0) begin #1 rst=1;#1;check;#1 rst=0;end
  @(posedge clk);#1;check;
 end
 @(negedge clk);clear=1;a=-128;b=-128;
 @(posedge clk);#1;check;
 @(negedge clk);clear=0;
 for(i=0;i<200000;i=i+1) begin @(posedge clk);#1;check;end
 $display("PASS mapped DSP PE: %0d checks, signed products, clears, between-edge reset pulses, accumulator overflow",checks);$finish;
end
endmodule
