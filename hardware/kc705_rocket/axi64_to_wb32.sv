`timescale 1ns/1ps
`default_nettype none
// One AXI transaction at a time, independent AW/W capture, aligned FIXED/INCR
// bursts. Narrow reads issue only the addressed 32-bit beat (MMIO side effects).
// Unsupported size, alignment, lock, burst or byte strobes return SLVERR.
module axi64_to_wb32 (
 input wire clk, rst,
 input wire aw_valid, output wire aw_ready, input wire [3:0] aw_id,
 input wire [31:0] aw_addr, input wire [7:0] aw_len,
 input wire [2:0] aw_size, input wire [1:0] aw_burst, input wire aw_lock,
 input wire w_valid, output wire w_ready, input wire [63:0] w_data,
 input wire [7:0] w_strb, input wire w_last,
 output wire b_valid, input wire b_ready, output wire [3:0] b_id,
 output wire [1:0] b_resp,
 input wire ar_valid, output wire ar_ready, input wire [3:0] ar_id,
 input wire [31:0] ar_addr, input wire [7:0] ar_len,
 input wire [2:0] ar_size, input wire [1:0] ar_burst, input wire ar_lock,
 output wire r_valid, input wire r_ready, output wire [3:0] r_id,
 output wire [63:0] r_data, output wire [1:0] r_resp, output wire r_last,
 output wire wb_cyc, output wire wb_stb, output wire wb_we,
 output wire [29:0] wb_adr, output wire [31:0] wb_dat_w,
 output wire [3:0] wb_sel, input wire [31:0] wb_dat_r,
 input wire wb_ack, wb_err
);
 localparam IDLE=0, READ=1, RRESP=2, WWAIT=3, WRITE=4, WNEXT=5, BRESP=6;
 reg [2:0] state;
 reg aw_pending, w_pending;
 reg [31:0] saved_aw_addr, addr;
 reg [7:0] saved_aw_len, remaining, strobes;
 reg [2:0] saved_aw_size, size;
 reg [1:0] saved_aw_burst, burst;
 reg [3:0] saved_aw_id, id;
 reg saved_aw_bad, bad, error, word_high, saved_last;
 reg [63:0] payload, response;
 function automatic invalid(input [31:0] a,input [2:0] s,input [1:0] b,input lock);
  invalid = s>3 || (a & ((32'b1<<s)-1))!=0 || b>1 || lock;
 endfunction
 wire [7:0] allowed_strobes = (8'hff >> (8-(1<<size))) << addr[2:0];
 wire invalid_strobes = (strobes & ~allowed_strobes)!=0;
 wire [3:0] selected_strobes = word_high ? strobes[7:4] : strobes[3:0];
 wire write_skip = bad || invalid_strobes || selected_strobes==0;
 wire read_skip = bad;
 wire word_done = wb_ack || wb_err;
 assign aw_ready = !rst && state==IDLE && !aw_pending;
 // One W beat may precede its AW. Never acknowledge more than is buffered.
 assign w_ready = !rst && !w_pending && (state==IDLE || state==WWAIT);
 assign ar_ready = !rst && state==IDLE && !aw_pending && !aw_valid;
 assign b_valid = !rst && state==BRESP;
 assign b_id=id; assign b_resp=error?2'b10:2'b00;
 assign r_valid = !rst && state==RRESP;
 assign r_id=id;assign r_data=response;assign r_resp=error?2'b10:2'b00;
 assign r_last=remaining==0;
 assign wb_cyc = !rst && ((state==READ&&!read_skip)||(state==WRITE&&!write_skip));
 assign wb_stb=wb_cyc; assign wb_we=state==WRITE;
 assign wb_adr={addr[31:3],word_high};
 assign wb_dat_w=word_high?payload[63:32]:payload[31:0];
 assign wb_sel=state==WRITE?selected_strobes:4'hf;
 always @(posedge clk) begin
  if(rst)begin
   state<=IDLE;aw_pending<=0;w_pending<=0;error<=0;bad<=0;
   saved_aw_addr<=0;saved_aw_len<=0;saved_aw_size<=0;saved_aw_burst<=0;saved_aw_id<=0;saved_aw_bad<=0;
   addr<=0;remaining<=0;size<=0;burst<=0;id<=0;strobes<=0;payload<=0;response<=0;word_high<=0;saved_last<=0;
  end else begin
   if(aw_valid&&aw_ready)begin
    aw_pending<=1;saved_aw_addr<=aw_addr;saved_aw_len<=aw_len;
    saved_aw_size<=aw_size;saved_aw_burst<=aw_burst;saved_aw_id<=aw_id;
    saved_aw_bad<=invalid(aw_addr,aw_size,aw_burst,aw_lock);
   end
   if(w_valid&&w_ready)begin w_pending<=1;payload<=w_data;strobes<=w_strb;saved_last<=w_last;end
   case(state)
    IDLE:begin
     if(aw_pending)begin
      addr<=saved_aw_addr;remaining<=saved_aw_len;size<=saved_aw_size;
      burst<=saved_aw_burst;id<=saved_aw_id;bad<=saved_aw_bad;error<=saved_aw_bad;
      aw_pending<=0;state<=WWAIT;
     end else if(ar_valid&&ar_ready)begin
      addr<=ar_addr;remaining<=ar_len;size<=ar_size;burst<=ar_burst;id<=ar_id;
      bad<=invalid(ar_addr,ar_size,ar_burst,ar_lock);error<=invalid(ar_addr,ar_size,ar_burst,ar_lock);
      response<=0;word_high<=ar_addr[2];state<=READ;
     end
    end
    READ:if(word_done||read_skip)begin
     if(word_high)response[63:32]<=read_skip?32'b0:wb_dat_r;
     else response[31:0]<=read_skip?32'b0:wb_dat_r;
     error<=error||wb_err;
     if(size==3&&!word_high)word_high<=1;
     else state<=RRESP;
    end
    RRESP:if(r_ready)begin
     if(remaining==0)state<=IDLE;
     else begin
      remaining<=remaining-1'b1;
      if(burst==1)begin addr<=addr+(32'b1<<size);word_high<=((addr+(32'b1<<size))&4)!=0;end
      else word_high<=addr[2];
      error<=bad;response<=0;state<=READ;
     end
    end
    WWAIT:if(w_pending)begin
     word_high<=size==3?1'b0:addr[2];state<=WRITE;
     error<=error||invalid_strobes||(saved_last!=(remaining==0));
    end
    WRITE:if(word_done||write_skip)begin
     error<=error||wb_err;
     if(size==3&&!word_high)word_high<=1;
     else begin w_pending<=0;state<=WNEXT;end
    end
    WNEXT:begin
     if(remaining==0)state<=BRESP;
     else begin remaining<=remaining-1'b1;if(burst==1)addr<=addr+(32'b1<<size);state<=WWAIT;end
    end
    BRESP:if(b_ready)state<=IDLE;
    default:state<=IDLE;
   endcase
  end
 end
endmodule
`default_nettype wire
