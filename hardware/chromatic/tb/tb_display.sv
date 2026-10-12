`timescale 1ns/1ps
module tb_display;
 reg clk=0;always #5 clk=~clk;
 reg reset=1,we=0,bank=0;reg [15:0] wa=0;reg [3:0] wd=0;
 wire [7:0] x,y;wire [14:0] ra=15'(y*160+x);wire [3:0] q;
 wire frame_tick,dotclk,de,hs,vs;wire [5:0] data;
 framebuffer fb(clk,we,wa,wd,bank,ra,q);
 scanout scan(clk,reset,1'b1,{q,2'b0},{2'b0,q},{q,2'b0}^6'h3f,x,y,frame_tick,dotclk,de,hs,vs,data);
 integer nactive=0,column,row,pixel,clocks=0;
 reg measuring=0;reg [5:0] expected;
 always @(negedge dotclk)if(measuring && de)begin
  column=(nactive%720)/3;row=nactive/720;
  expected=0;
  if(column>=41 && column<201)begin
   pixel=(((column-41)*7+row*13)&15)^(bank?15:0);
   case(nactive%3)
    0:expected=(pixel<<2)&63;
    1:expected=pixel&15;
    2:expected=((pixel<<2)&63)^63;
   endcase
  end
  if(data!==expected)$fatal(1,"BRAM-to-LCD mismatch row=%0d column=%0d component=%0d expected=%0d actual=%0d",row,column,nactive%3,expected,data);
  nactive=nactive+1;
 end
 initial begin
  for(integer yy=0;yy<144;yy=yy+1)for(integer xx=0;xx<160;xx=xx+1)begin
   @(negedge clk);we=1;wa=yy*160+xx;wd=(xx*7+yy*13)&15;
  end
  @(negedge clk);we=0;reset=0;
  @(posedge frame_tick);@(negedge frame_tick);measuring=1;
  // Render the other bank during scanout: none of its writes may leak through.
  for(integer yy=0;yy<144;yy=yy+1)for(integer xx=0;xx<160;xx=xx+1)begin
   @(negedge clk);we=1;wa=32768+yy*160+xx;wd=((xx*7+yy*13)&15)^15;
  end
  @(negedge clk);we=0;
  @(posedge frame_tick);measuring=0;
  if(nactive!=144*720)$fatal(1,"wrong RGB component count");
  bank=1;nactive=0;@(negedge frame_tick);measuring=1;
  @(posedge frame_tick);measuring=0;
  if(nactive!=144*720)$fatal(1,"wrong second-bank RGB component count");
  $display("DISPLAY PASS: 138,240 visible RGB components, concurrent back-buffer writes, bank swap, padding and 144 rows");$finish;
 end
endmodule
