`timescale 1ns/1ps
`default_nettype none
// One ordered CPU transaction maps to one accelerator AXI-Lite transaction.
// Unlike the stream mailbox, this port needs no software command envelope.
// Request and response payloads remain stable until their respective handshakes.
module tiny3tpu_direct_peripheral (
    input wire clk, input wire rst_n,
    input wire req_valid, output wire req_ready,
    input wire req_write, input wire [7:0] req_addr,
    input wire [31:0] req_wdata, input wire [3:0] req_wstrb,
    output reg resp_valid, input wire resp_ready,
    output reg [31:0] resp_rdata, output reg resp_error
);
    reg active, writing;
    reg [7:0] address;
    reg [31:0] data;
    reg [3:0] strobe;
    reg awvalid,wvalid,arvalid;
    wire awready,wready,arready,bvalid,rvalid;
    wire [1:0] bresp,rresp;
    wire [31:0] rdata;
    assign req_ready = !active && !resp_valid;
    wire bready=active && writing && !resp_valid;
    wire rready=active && !writing && !resp_valid;
    tiny3tpu_axi accelerator (
        .s_axi_aclk(clk),.s_axi_aresetn(rst_n),
        .s_axi_awaddr(address),.s_axi_awprot(3'b0),
        .s_axi_awvalid(awvalid),.s_axi_awready(awready),
        .s_axi_wdata(data),.s_axi_wstrb(strobe),
        .s_axi_wvalid(wvalid),.s_axi_wready(wready),
        .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
        .s_axi_araddr(address),.s_axi_arprot(3'b0),
        .s_axi_arvalid(arvalid),.s_axi_arready(arready),
        .s_axi_rdata(rdata),.s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid),.s_axi_rready(rready)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            active<=0;writing<=0;address<=0;data<=0;strobe<=0;
            awvalid<=0;wvalid<=0;arvalid<=0;
            resp_valid<=0;resp_rdata<=0;resp_error<=0;
        end else begin
            if(resp_valid && resp_ready)resp_valid<=0;
            if(awvalid && awready)awvalid<=0;
            if(wvalid && wready)wvalid<=0;
            if(arvalid && arready)arvalid<=0;
            if(req_valid && req_ready)begin
                active<=1;writing<=req_write;address<=req_addr;
                data<=req_wdata;strobe<=req_wstrb;
                awvalid<=req_write;wvalid<=req_write;arvalid<=!req_write;
            end
            if(bvalid && bready)begin
                active<=0;resp_valid<=1;resp_rdata<=0;resp_error<=bresp!=0;
            end else if(rvalid && rready)begin
                active<=0;resp_valid<=1;resp_rdata<=rdata;resp_error<=rresp!=0;
            end
        end
    end
endmodule
`default_nettype wire
