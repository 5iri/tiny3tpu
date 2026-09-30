`timescale 1ns/1ps
`default_nettype none
// Binary32 exp(x), positive result. Serial hyperbolic CORDIC, Q3.29,
// shifts 1..30 with required repetitions at 4 and 13. Fixed input Q8.24.
// Ready/valid output holds under backpressure. Reset cancels pending work.
module tiny3tpu_cordic_exp(
 input wire clk,input wire rst,input wire in_valid,output wire in_ready,
 input wire [31:0] in_bits,output reg out_valid,input wire out_ready,
 output reg [31:0] out_bits
);
 localparam IDLE=0,FIX=1,SCALE=2,REDUCE=3,ROTATE=4,PACK=5;
 reg [2:0] state=IDLE;
 reg [31:0] bits;
 reg signed [31:0] fixed_x,x,y,z;
 reg signed [63:0] range_x;
 reg signed [8:0] n;
 reg [5:0] iteration;
 reg [5:0] shift;
 reg signed [31:0] angle;
 assign in_ready=state==IDLE&&!out_valid;
 always @* begin
  shift=1;angle=0;
  case(iteration)
            6'd1: begin shift=6'd1;angle=32'sd294906491;end
            6'd2: begin shift=6'd2;angle=32'sd137123709;end
            6'd3: begin shift=6'd3;angle=32'sd67461703;end
            6'd4: begin shift=6'd4;angle=32'sd33598225;end
            6'd5: begin shift=6'd4;angle=32'sd33598225;end
            6'd6: begin shift=6'd5;angle=32'sd16782681;end
            6'd7: begin shift=6'd6;angle=32'sd8389291;end
            6'd8: begin shift=6'd7;angle=32'sd4194389;end
            6'd9: begin shift=6'd8;angle=32'sd2097163;end
            6'd10: begin shift=6'd9;angle=32'sd1048577;end
            6'd11: begin shift=6'd10;angle=32'sd524288;end
            6'd12: begin shift=6'd11;angle=32'sd262144;end
            6'd13: begin shift=6'd12;angle=32'sd131072;end
            6'd14: begin shift=6'd13;angle=32'sd65536;end
            6'd15: begin shift=6'd13;angle=32'sd65536;end
            6'd16: begin shift=6'd14;angle=32'sd32768;end
            6'd17: begin shift=6'd15;angle=32'sd16384;end
            6'd18: begin shift=6'd16;angle=32'sd8192;end
            6'd19: begin shift=6'd17;angle=32'sd4096;end
            6'd20: begin shift=6'd18;angle=32'sd2048;end
            6'd21: begin shift=6'd19;angle=32'sd1024;end
            6'd22: begin shift=6'd20;angle=32'sd512;end
            6'd23: begin shift=6'd21;angle=32'sd256;end
            6'd24: begin shift=6'd22;angle=32'sd128;end
            6'd25: begin shift=6'd23;angle=32'sd64;end
            6'd26: begin shift=6'd24;angle=32'sd32;end
            6'd27: begin shift=6'd25;angle=32'sd16;end
            6'd28: begin shift=6'd26;angle=32'sd8;end
            6'd29: begin shift=6'd27;angle=32'sd4;end
            6'd30: begin shift=6'd28;angle=32'sd2;end
            6'd31: begin shift=6'd29;angle=32'sd1;end
            6'd32: begin shift=6'd30;angle=32'sd0;end
   default:begin shift=30;angle=0;end
  endcase
 end
 wire [31:0] magnitude=bits&32'h7fffffff;
 wire [23:0] significand={1'b1,bits[22:0]};
 wire signed [9:0] fix_shift=$signed({2'b0,bits[30:23]})-10'sd126;
 wire [31:0] unsigned_fixed=bits[30:23]==0?0:
    fix_shift>=0?({8'b0,significand}<<fix_shift):
    -fix_shift>=32?0:({8'b0,significand}>>(-fix_shift));
 wire signed [31:0] x_next=z>=0?x+(y>>>shift):x-(y>>>shift);
 wire signed [31:0] y_next=z>=0?y+(x>>>shift):y-(x>>>shift);
 wire signed [31:0] z_next=z>=0?z-angle:z+angle;
 wire [31:0] sum=x+y;
 reg [5:0] msb,right;
 reg signed [10:0] exponent;
 reg [31:0] quotient,mask,remainder,half;
 reg [32:0] rounded;
 reg [31:0] packed_result;
 integer i;
 always @* begin
  msb=0;for(i=0;i<32;i=i+1)if(sum[i])msb=i;
  exponent=$signed({1'b0,msb})-11'sd29+$signed(n);
  right=exponent< -126? -$signed(n)-11'sd120:msb-6'd23;
  quotient=sum>>right;
  mask=(32'h1<<right)-1;remainder=sum&mask;half=32'h1<<(right-1);
  rounded={1'b0,quotient}+((remainder>half)||((remainder==half)&&quotient[0]));
  packed_result=0;
  if(exponent< -126)packed_result=rounded[31:0];
  else begin
   if(rounded[24])begin rounded=rounded>>1;exponent=exponent+1;end
   if(exponent>127)packed_result=32'h7f800000;
   else packed_result={1'b0,8'(exponent+127),rounded[22:0]};
  end
 end
 always @(posedge clk)begin
  if(rst)begin state<=IDLE;out_valid<=0;out_bits<=0;bits<=0;fixed_x<=0;range_x<=0;n<=0;x<=0;y<=0;z<=0;iteration<=0;end
  else begin
   if(out_valid&&out_ready)out_valid<=0;
   case(state)
    IDLE:if(in_valid&&in_ready)begin bits<=in_bits;state<=FIX;end
    FIX:begin
     if(magnitude>32'h7f800000)begin out_bits<=bits|32'h00400000;out_valid<=1;state<=IDLE;end
     else if(!bits[31]&&bits>32'h42b17217)begin out_bits<=32'h7f800000;out_valid<=1;state<=IDLE;end
     else if(bits[31]&&magnitude>32'h42cff1b4)begin out_bits<=0;out_valid<=1;state<=IDLE;end
     else begin fixed_x<=bits[31]?-$signed(unsigned_fixed):$signed(unsigned_fixed);state<=SCALE;end
    end
    // Range reduction uses the same shift/add architecture: no multipliers
    // or DSP timing profiles. At most 150 ln(2) subtractions over the finite
    // exp domain; softmax inputs typically require only a few reductions.
    SCALE:begin range_x<=$signed({{32{fixed_x[31]}},fixed_x})<<<5;n<=0;state<=REDUCE;end
    REDUCE:begin
     if(range_x>64'sd186065280)begin range_x<=range_x-64'sd372130559;n<=n+1;end
     else if(range_x< -64'sd186065280)begin range_x<=range_x+64'sd372130559;n<=n-1;end
     else begin state<=ROTATE;iteration<=1;x<=32'sd648270052;y<=0;z<=range_x[31:0];end
    end
    ROTATE:begin
     x<=x_next;y<=y_next;z<=z_next;if(iteration==32)state<=PACK;else iteration<=iteration+1;
    end
    PACK:begin out_bits<=packed_result;out_valid<=1;state<=IDLE;end
   endcase
  end
 end
endmodule
`default_nettype wire
