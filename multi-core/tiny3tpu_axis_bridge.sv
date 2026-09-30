`timescale 1ns/1ps
`default_nettype none

// Two-beat AXI-Stream register commands -> one AXI4-Lite transaction.
// See docs_synapse32_stream.md. One outstanding command; no speculative IO.
// All connected interfaces must share clk and reset. No bus timeout: once an
// AXI transaction starts, only completion or a coordinated reset can retire it.
module tiny3tpu_axis_bridge (
    input wire clk, input wire rst_n,
    input wire [31:0] s_axis_tdata, input wire [3:0] s_axis_tkeep,
    input wire s_axis_tlast, input wire s_axis_tvalid,
    output wire s_axis_tready,
    output wire [31:0] m_axis_tdata, output wire [3:0] m_axis_tkeep,
    output wire m_axis_tlast, output wire m_axis_tvalid,
    input wire m_axis_tready,
    output wire [7:0] m_axi_awaddr, output wire [2:0] m_axi_awprot,
    output wire m_axi_awvalid, input wire m_axi_awready,
    output wire [31:0] m_axi_wdata, output wire [3:0] m_axi_wstrb,
    output wire m_axi_wvalid, input wire m_axi_wready,
    input wire [1:0] m_axi_bresp, input wire m_axi_bvalid,
    output wire m_axi_bready,
    output wire [7:0] m_axi_araddr, output wire [2:0] m_axi_arprot,
    output wire m_axi_arvalid, input wire m_axi_arready,
    input wire [31:0] m_axi_rdata, input wire [1:0] m_axi_rresp,
    input wire m_axi_rvalid, output wire m_axi_rready
);
    localparam [3:0] HEADER=0, PAYLOAD=1, DRAIN=2, WRITE=3,
        WRITE_RESP=4, READ_ADDR=5, READ_RESP=6, RESP_CODE=7, RESP_DATA=8;
    reg [3:0] state;
    reg [7:0] addr;
    reg [3:0] strb;
    reg write_cmd, bad_header;
    reg [31:0] payload, response_data;
    reg [1:0] response_code;
    reg aw_done, w_done;
    assign s_axis_tready = rst_n && (state==HEADER || state==PAYLOAD || state==DRAIN);
    assign m_axis_tvalid = rst_n && (state==RESP_CODE || state==RESP_DATA);
    assign m_axis_tdata = state==RESP_CODE ? {30'b0,response_code} : response_data;
    assign m_axis_tkeep = 4'hf;
    assign m_axis_tlast = state==RESP_DATA;
    assign m_axi_awaddr=addr;
    assign m_axi_araddr=addr;
    assign m_axi_awprot=3'b0;
    assign m_axi_arprot=3'b0;
    assign m_axi_wdata=payload;
    assign m_axi_wstrb=strb;
    assign m_axi_awvalid=rst_n && state==WRITE && !aw_done;
    assign m_axi_wvalid=rst_n && state==WRITE && !w_done;
    assign m_axi_bready=rst_n && state==WRITE_RESP;
    assign m_axi_arvalid=rst_n && state==READ_ADDR;
    assign m_axi_rready=rst_n && state==READ_RESP;

    always @(posedge clk) begin
        if (!rst_n) begin
            state<=HEADER; addr<=0; strb<=0; write_cmd<=0; bad_header<=0;
            payload<=0; response_data<=0; response_code<=0;
            aw_done<=0; w_done<=0;
        end else begin
            case (state)
                HEADER: if (s_axis_tvalid) begin
                    addr<=s_axis_tdata[7:0]; strb<=s_axis_tdata[15:12];
                    write_cmd<=s_axis_tdata[8];
                    bad_header<=s_axis_tkeep!=4'hf ||
                        s_axis_tdata[31:16]!=0 || s_axis_tdata[11:9]!=0;
                    response_data<=0; response_code<=2'b10;
                    if (s_axis_tlast) state<=RESP_CODE;
                    else state<=PAYLOAD;
                end
                PAYLOAD: if (s_axis_tvalid) begin
                    payload<=s_axis_tdata;
                    if (!s_axis_tlast) state<=DRAIN;
                    else if (bad_header || s_axis_tkeep!=4'hf) state<=RESP_CODE;
                    else if (write_cmd) begin
                        aw_done<=0; w_done<=0; state<=WRITE;
                    end else state<=READ_ADDR;
                end
                // Overlong frames are rejected in full, up to TLAST. No AXI
                // side effects occur for any malformed packet.
                DRAIN: if (s_axis_tvalid && s_axis_tlast) state<=RESP_CODE;
                WRITE: begin
                    if (m_axi_awready) aw_done<=1;
                    if (m_axi_wready) w_done<=1;
                    if ((aw_done || m_axi_awready) && (w_done || m_axi_wready))
                        state<=WRITE_RESP;
                end
                WRITE_RESP: if (m_axi_bvalid) begin
                    response_code<=m_axi_bresp; state<=RESP_CODE;
                end
                READ_ADDR: if (m_axi_arready) state<=READ_RESP;
                READ_RESP: if (m_axi_rvalid) begin
                    response_code<=m_axi_rresp; response_data<=m_axi_rdata;
                    state<=RESP_CODE;
                end
                RESP_CODE: if (m_axis_tready) state<=RESP_DATA;
                RESP_DATA: if (m_axis_tready) state<=HEADER;
                default: state<=HEADER;
            endcase
        end
    end
endmodule
`default_nettype wire
