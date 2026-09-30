// Diagnostic-only CPU/RAM observer, independent UART status transmitter.
module cpu_observer(input clk_p,clk_n,reset_btn, output uart_tx, output [7:0] led);
wire rawclk,pllclk,fb,locked,clk;
IBUFDS ib(.I(clk_p),.IB(clk_n),.O(rawclk));
PLLE2_ADV #(.CLKFBOUT_MULT(8),.CLKIN1_PERIOD(5.0),.CLKOUT0_DIVIDE(16),.DIVCLK_DIVIDE(1),.STARTUP_WAIT("FALSE")) pll(.CLKIN1(rawclk),.CLKIN2(1'b0),.CLKINSEL(1'b1),.CLKFBIN(fb),.CLKFBOUT(fb),.CLKOUT0(pllclk),.LOCKED(locked),.RST(1'b0),.PWRDWN(1'b0),.DADDR(7'b0),.DCLK(1'b0),.DEN(1'b0),.DI(16'b0),.DWE(1'b0));
BUFG bg(.I(pllclk),.O(clk));
reg [15:0] startup=0; reg [1:0] btn=0;
always @(posedge clk) begin btn<={btn[0],reset_btn};if(!locked || btn[1])startup<=0;else if(!(&startup))startup<=startup+1'b1;end
wire rst=!(&startup);wire ready_to_run=locked&&!rst;
wire [31:0] pc_debug;wire fault;
    wire cpu_clk, cpu_step;
    wire [31:0] instr, cpu_rdata, rd_addr, wr_addr, wr_data;
    wire rd_en, wr_en;
    wire [3:0] wr_strb;
    wire [2:0] load_type;
    synapse32_clock_enable clock_enable (
        .clk(clk), .enable(rst || cpu_step), .cpu_clk(cpu_clk)
    );
    riscv_cpu cpu (
        .system_clk(clk),
        .clk(cpu_clk), .rst(rst), .module_instr_in(instr),
        .module_read_data_in(cpu_rdata), .module_pc_out(pc_debug),
        .module_wr_data_out(wr_data), .module_mem_wr_en(wr_en),
        .module_mem_rd_en(rd_en), .module_read_addr(rd_addr),
        .module_write_addr(wr_addr), .module_write_byte_enable(wr_strb),
        .module_load_type(load_type), .module_load_page_fault_in(1'b0),
        .module_store_page_fault_in(1'b0), .module_page_fault_addr_in(32'b0),
        .module_instr_page_fault_in(1'b0), .module_data_mmu_enable_out(),
        .module_data_privilege_out(), .module_satp_out(),
        .module_data_sum_out(), .module_data_mxr_out(),
        .module_instr_mmu_enable_out(), .module_instr_privilege_out(),
        .timer_interrupt(1'b0), .software_interrupt(1'b0), .external_interrupt(1'b0)
    );
    wire req_valid, req_ready, req_write, resp_valid, resp_ready, resp_error;
    wire [31:0] req_addr, req_wdata, resp_rdata;
    wire [3:0] req_wstrb;
    synapse32_memory_sequencer sequencer (
        .clk(clk), .rst(rst), .ready_to_run(ready_to_run),
        .cpu_pc(pc_debug), .cpu_rd_en(rd_en), .cpu_wr_en(wr_en),
        .cpu_rd_addr(rd_addr), .cpu_wr_addr(wr_addr), .cpu_wdata(wr_data),
        .cpu_wstrb(wr_strb), .cpu_load_type(load_type),
        .cpu_instr(instr), .cpu_rdata(cpu_rdata), .cpu_step(cpu_step), .fault(fault),
        .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write),
        .req_addr(req_addr), .req_wdata(req_wdata), .req_wstrb(req_wstrb),
        .resp_valid(resp_valid), .resp_ready(resp_ready),
        .resp_rdata(resp_rdata), .resp_error(resp_error)
    );

reg local_valid=0,local_error=0;reg [31:0] local_data=0;
wire boot_address=req_addr[31:16]==16'h8000;
assign req_ready=!rst&&!local_valid;
wire accept=req_valid&&req_ready;
assign resp_valid=local_valid;assign resp_error=local_error;assign resp_rdata=local_data;
(* ram_style="block" *) reg [31:0] boot_mem[0:16383];
initial $readmemh("build-kc705-cpu-stage1-led/firmware.hex",boot_mem);
integer lane;
always @(posedge clk)begin
 if(rst)begin local_valid<=0;local_error<=0;end
 else begin
 if(resp_valid&&resp_ready)local_valid<=0;
 if(accept)begin
 local_valid<=1;local_error<=0;
 if(boot_address)begin
 local_data<=boot_mem[req_addr[15:2]];
 if(req_write)for(lane=0;lane<4;lane=lane+1)if(req_wstrb[lane])boot_mem[req_addr[15:2]][lane*8+:8]<=req_wdata[lane*8+:8];
 end else if(req_addr==32'h20002000)local_data<=0;
 else begin local_data<=0;local_error<=1;end
 end
 end
end
reg cpu_seen=0;
always @(posedge cpu_clk)if(rst)cpu_seen<=0;else cpu_seen<=1;
reg [7:0] events=0;reg [26:0] heartbeat=0;
always @(posedge clk)begin
 heartbeat<=heartbeat+1'b1;
 if(rst)events<=0;
 else begin
 events[0]<=1;
 if(cpu_seen)events[1]<=1;
 if(accept&&boot_address&&!req_write)events[2]<=1;
 if(instr!=0)events[3]<=1;
 if(pc_debug!=32'h80000000)events[4]<=1;
 if(accept&&req_write&&req_addr==32'h20002000)events[5]<=1;
 if(fault)events[6]<=1;
 if(cpu_step)events[7]<=1;
 end
end
assign led={heartbeat[26],events[6],events[5],events[4],events[2],cpu_seen,!rst,locked};
// Observer uses system clock, independent of CPU progress. 16-byte LE packets.
wire [127:0] snapshot={req_addr,instr,pc_debug,{4'b0,fault,cpu_step,rst,locked},events,16'h5aa5};
reg [127:0] packet=0;reg [3:0] byte_index=15,bit_index=9;
reg [9:0] tx_shift=10'h3ff;reg [9:0] baud_count=0;
assign uart_tx=tx_shift[0];
always @(posedge clk)begin
 if(!locked)begin baud_count<=0;bit_index<=9;byte_index<=15;tx_shift<=10'h3ff;packet<=0;end
 else if(baud_count==867)begin
 baud_count<=0;
 if(bit_index==9)begin
 bit_index<=0;
 if(byte_index==15)begin tx_shift<={1'b1,snapshot[7:0],1'b0};packet<=snapshot>>8;byte_index<=0;end
 else begin tx_shift<={1'b1,packet[7:0],1'b0};packet<=packet>>8;byte_index<=byte_index+1'b1;end
 end else begin tx_shift<={1'b1,tx_shift[9:1]};bit_index<=bit_index+1'b1;end
 end else baud_count<=baud_count+1'b1;
end
endmodule
