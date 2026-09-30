`timescale 1ns/1ps
`default_nettype none
// Word registers: 0 control/status, 4 binary32 input, 8 binary32 output,
// 12 identity (EXP1). Control bit0 start, bit1 clear; status bit0 busy,
// bit1 done, bit2 rejected command. A rejected start never overwrites input work.
module tiny3tpu_cordic_mmio(
 input wire clk,input wire rst,input wire wr,input wire [3:0] addr,
 input wire [31:0] wdata,input wire [3:0] wstrb,output reg [31:0] rdata
);
 reg [31:0] argument,result;
 reg done,rejected;
 wire ready,valid;wire [31:0] value;
 wire control=wr&&addr==0&&wstrb==15;
 wire start=control&&wdata[0]&&ready;
 tiny3tpu_cordic_exp core(.clk(clk),.rst(rst),.in_valid(start),.in_ready(ready),
   .in_bits(argument),.out_valid(valid),.out_ready(1'b1),.out_bits(value));
 always @*begin
  case(addr)
   0:rdata={29'b0,rejected,done,!ready};
   4:rdata=argument;
   8:rdata=result;
   12:rdata=32'h45585031;
   default:rdata=0;
  endcase
 end
 always @(posedge clk)begin
  if(rst)begin argument<=0;result<=0;done<=0;rejected<=0;end
  else begin
   if(control&&wdata[1])begin done<=0;rejected<=0;end
   if(control&&wdata[0])begin
    if(ready)done<=0;
    else rejected<=1;
   end
   if(wr&&addr==4&&wstrb==15)argument<=wdata;
   if(valid)begin result<=value;done<=1;end
  end
 end
endmodule
`default_nettype wire
