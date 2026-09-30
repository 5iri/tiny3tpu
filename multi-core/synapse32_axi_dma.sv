`timescale 1ns/1ps
`default_nettype none
// Open RTL AXI DMA with a small native CPU register interface. This is not the
// AMD register ABI. One full-duplex batch owns the TPU until both descriptors
// complete, including all AXI write responses. Reset is system-wide only.
module synapse32_axi_dma (
    input wire clk, input wire rst, input wire legacy_idle,
    input wire cpu_wr_en, input wire cpu_rd_en,
    input wire [4:0] cpu_addr, input wire [31:0] cpu_wdata,
    input wire [3:0] cpu_wstrb, output reg [31:0] cpu_rdata,
    output reg busy, output wire irq,
    output wire [31:0] cmd_data, output wire [3:0] cmd_keep,
    output wire cmd_last, output wire cmd_valid, input wire cmd_ready,
    input wire [31:0] resp_data, input wire [3:0] resp_keep,
    input wire resp_last, input wire resp_valid, output wire resp_ready,
    output wire [0:0] m_axi_awid, output wire [31:0] m_axi_awaddr,
    output wire [7:0] m_axi_awlen, output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst, output wire m_axi_awlock,
    output wire [3:0] m_axi_awcache, output wire [2:0] m_axi_awprot,
    output wire m_axi_awvalid, input wire m_axi_awready,
    output wire [31:0] m_axi_wdata, output wire [3:0] m_axi_wstrb,
    output wire m_axi_wlast, output wire m_axi_wvalid, input wire m_axi_wready,
    input wire [0:0] m_axi_bid, input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid, output wire m_axi_bready,
    output wire [0:0] m_axi_arid, output wire [31:0] m_axi_araddr,
    output wire [7:0] m_axi_arlen, output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst, output wire m_axi_arlock,
    output wire [3:0] m_axi_arcache, output wire [2:0] m_axi_arprot,
    output wire m_axi_arvalid, input wire m_axi_arready,
    input wire [0:0] m_axi_rid, input wire [31:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp, input wire m_axi_rlast,
    input wire m_axi_rvalid, output wire m_axi_rready
);
    reg [31:0] tx_address, rx_address, byte_count;
    // Keep each span end current on the accepted descriptor write. START sees
    // the updated value on the next cycle, including when that write was last.
    reg [32:0] tx_end_q, rx_end_q;
    reg [31:0] tx_active, rx_active;
    reg [15:0] length_active;
    reg done, error, misuse;
    reg [3:0] read_error, write_error;
    reg read_pending, write_pending, read_complete, write_complete;
    wire read_ready, write_ready, read_status_valid, write_status_valid;
    wire [3:0] read_status_error, write_status_error;
    wire [15:0] write_status_length;
    wire [31:0] tx_data, rx_data;
    wire [3:0] tx_keep, rx_keep;
    wire tx_valid, tx_ready, tx_last, rx_valid, rx_ready, rx_last;
    wire batch_protocol_error, batch_command_error;
    wire descriptor_valid = byte_count!=0 && byte_count[31:16]==0 && byte_count[2:0]==0 &&
        tx_address[1:0]==0 && rx_address[1:0]==0 &&
        tx_address[31:30]==2'b01 && rx_address[31:30]==2'b01 &&
        tx_end_q<=33'h080000000 && rx_end_q<=33'h080000000 &&
        (tx_end_q<={1'b0,rx_address} || rx_end_q<={1'b0,tx_address});
    wire write_ok=cpu_wr_en && cpu_wstrb==4'hf && cpu_addr[1:0]==0;
    wire start_request=write_ok && cpu_addr==5'h0c && cpu_wdata==1;
    wire batch_start=start_request && !busy && !done && legacy_idle && descriptor_valid;
    assign irq=done;
    always @* begin
        cpu_rdata=0;
        if (cpu_rd_en) case (cpu_addr)
            5'h00: cpu_rdata=tx_address;
            5'h04: cpu_rdata=rx_address;
            5'h08: cpu_rdata=byte_count;
            5'h10: cpu_rdata={28'b0,misuse,error,done,busy};
            5'h14: cpu_rdata={28'b0,read_error};
            5'h18: cpu_rdata={28'b0,write_error};
            5'h1c: cpu_rdata=32'h54444d31; // TDM1 register ABI.
            default: cpu_rdata=0;
        endcase
    end
    always @(posedge clk) begin
        if (rst) begin
            tx_address<=0; rx_address<=0; byte_count<=0;
            tx_end_q<=0; rx_end_q<=0;
            tx_active<=0; rx_active<=0; length_active<=0;
            busy<=0; done<=0; error<=0; misuse<=0;
            read_error<=0; write_error<=0;
            read_pending<=0; write_pending<=0; read_complete<=0; write_complete<=0;
        end else begin
            if (read_pending && read_ready) read_pending<=0;
            if (write_pending && write_ready) write_pending<=0;
            if (busy) begin
                if (batch_protocol_error || batch_command_error) error<=1;
                if (read_status_valid) begin
                    read_complete<=1; read_error<=read_status_error;
                    if (read_status_error!=0) error<=1;
                end
                if (write_status_valid) begin
                    write_complete<=1; write_error<=write_status_error;
                    if (write_status_error!=0 || write_status_length!=length_active) error<=1;
                end
                if ((read_complete || read_status_valid) && (write_complete || write_status_valid)) begin
                    busy<=0; done<=1;
                end
            end
            if (cpu_wr_en) begin
                if (!write_ok) misuse<=1;
                else case (cpu_addr)
                    5'h00: if (!busy) begin
                        tx_address<=cpu_wdata;
                        tx_end_q<={1'b0,cpu_wdata}+{1'b0,byte_count};
                    end else misuse<=1;
                    5'h04: if (!busy) begin
                        rx_address<=cpu_wdata;
                        rx_end_q<={1'b0,cpu_wdata}+{1'b0,byte_count};
                    end else misuse<=1;
                    5'h08: if (!busy) begin
                        byte_count<=cpu_wdata;
                        tx_end_q<={1'b0,tx_address}+{1'b0,cpu_wdata};
                        rx_end_q<={1'b0,rx_address}+{1'b0,cpu_wdata};
                    end else misuse<=1;
                    5'h0c: begin
                        if (cpu_wdata==1) begin
                            if (busy || done) misuse<=1;
                            else if (!descriptor_valid || !legacy_idle) begin done<=1; error<=1; end
                            else begin
                                tx_active<=tx_address; rx_active<=rx_address; length_active<=byte_count[15:0];
                                busy<=1; done<=0; error<=0; misuse<=0;
                                read_error<=0; write_error<=0;
                                read_pending<=1; write_pending<=1; read_complete<=0; write_complete<=0;
                            end
                        end else if (cpu_wdata==2 && !busy && done) begin
                            done<=0; error<=0; misuse<=0; read_error<=0; write_error<=0;
                        end else misuse<=1;
                    end
                    default: misuse<=1;
                endcase
            end
        end
    end
    tiny3tpu_dma_batch framing (
        .clk(clk),.rst(rst),.start(batch_start),.word_count(byte_count[17:2]),
        .protocol_error(batch_protocol_error),.command_error(batch_command_error),
        .s_tx_data(tx_data),.s_tx_keep(tx_keep),.s_tx_last(tx_last),.s_tx_valid(tx_valid),.s_tx_ready(tx_ready),
        .m_cmd_data(cmd_data),.m_cmd_keep(cmd_keep),.m_cmd_last(cmd_last),.m_cmd_valid(cmd_valid),.m_cmd_ready(cmd_ready),
        .s_resp_data(resp_data),.s_resp_keep(resp_keep),.s_resp_last(resp_last),.s_resp_valid(resp_valid),.s_resp_ready(resp_ready),
        .m_rx_data(rx_data),.m_rx_keep(rx_keep),.m_rx_last(rx_last),.m_rx_valid(rx_valid),.m_rx_ready(rx_ready)
    );
    axi_dma #(.AXI_DATA_WIDTH(32),.AXI_ADDR_WIDTH(32),.AXI_ID_WIDTH(1),
        .AXI_MAX_BURST_LEN(16),.AXIS_ID_WIDTH(1),.AXIS_DEST_WIDTH(1),.AXIS_USER_WIDTH(1),
        .AXIS_USER_ENABLE(0),.LEN_WIDTH(16),.TAG_WIDTH(1),.ENABLE_SG(0),.ENABLE_UNALIGNED(0)) engine (
        .clk(clk),.rst(rst),
        .s_axis_read_desc_addr(tx_active),.s_axis_read_desc_len(length_active),.s_axis_read_desc_tag(1'b0),
        .s_axis_read_desc_id(1'b0),.s_axis_read_desc_dest(1'b0),.s_axis_read_desc_user(1'b0),
        .s_axis_read_desc_valid(read_pending),.s_axis_read_desc_ready(read_ready),
        .m_axis_read_desc_status_tag(),.m_axis_read_desc_status_error(read_status_error),.m_axis_read_desc_status_valid(read_status_valid),
        .m_axis_read_data_tdata(tx_data),.m_axis_read_data_tkeep(tx_keep),.m_axis_read_data_tvalid(tx_valid),
        .m_axis_read_data_tready(tx_ready),.m_axis_read_data_tlast(tx_last),
        .m_axis_read_data_tid(),.m_axis_read_data_tdest(),.m_axis_read_data_tuser(),
        .s_axis_write_desc_addr(rx_active),.s_axis_write_desc_len(length_active),.s_axis_write_desc_tag(1'b0),
        .s_axis_write_desc_valid(write_pending),.s_axis_write_desc_ready(write_ready),
        .m_axis_write_desc_status_len(write_status_length),.m_axis_write_desc_status_tag(),
        .m_axis_write_desc_status_id(),.m_axis_write_desc_status_dest(),.m_axis_write_desc_status_user(),
        .m_axis_write_desc_status_error(write_status_error),.m_axis_write_desc_status_valid(write_status_valid),
        .s_axis_write_data_tdata(rx_data),.s_axis_write_data_tkeep(rx_keep),.s_axis_write_data_tvalid(rx_valid),
        .s_axis_write_data_tready(rx_ready),.s_axis_write_data_tlast(rx_last),
        .s_axis_write_data_tid(1'b0),.s_axis_write_data_tdest(1'b0),.s_axis_write_data_tuser(1'b0),
        .m_axi_awid(m_axi_awid),.m_axi_awaddr(m_axi_awaddr),.m_axi_awlen(m_axi_awlen),.m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),.m_axi_awlock(m_axi_awlock),.m_axi_awcache(m_axi_awcache),.m_axi_awprot(m_axi_awprot),
        .m_axi_awvalid(m_axi_awvalid),.m_axi_awready(m_axi_awready),
        .m_axi_wdata(m_axi_wdata),.m_axi_wstrb(m_axi_wstrb),.m_axi_wlast(m_axi_wlast),.m_axi_wvalid(m_axi_wvalid),.m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid),.m_axi_bresp(m_axi_bresp),.m_axi_bvalid(m_axi_bvalid),.m_axi_bready(m_axi_bready),
        .m_axi_arid(m_axi_arid),.m_axi_araddr(m_axi_araddr),.m_axi_arlen(m_axi_arlen),.m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),.m_axi_arlock(m_axi_arlock),.m_axi_arcache(m_axi_arcache),.m_axi_arprot(m_axi_arprot),
        .m_axi_arvalid(m_axi_arvalid),.m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid),.m_axi_rdata(m_axi_rdata),.m_axi_rresp(m_axi_rresp),.m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid),.m_axi_rready(m_axi_rready),
        .read_enable(1'b1),.write_enable(1'b1),.write_abort(1'b0)
    );
endmodule
`default_nettype wire
