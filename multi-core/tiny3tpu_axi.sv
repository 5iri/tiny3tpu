`timescale 1ns/1ps

// Fixed FPGA-facing AXI4-Lite wrapper for the two-core 4x4 accelerator.
//
// The AXI channels are deliberately handled independently: AW and W may be
// presented in either order and are committed as one write only after both
// have been accepted.  There is one outstanding write response and one
// outstanding read response.
module tiny3tpu_axi (
    input  wire        s_axi_aclk,
    input  wire        s_axi_aresetn,

    input  wire [7:0]  s_axi_awaddr,
    input  wire [2:0]  s_axi_awprot,
    input  wire        s_axi_awvalid,
    output wire        s_axi_awready,

    input  wire [31:0] s_axi_wdata,
    input  wire [3:0]  s_axi_wstrb,
    input  wire        s_axi_wvalid,
    output wire        s_axi_wready,

    output wire [1:0]  s_axi_bresp,
    output wire        s_axi_bvalid,
    input  wire        s_axi_bready,

    input  wire [7:0]  s_axi_araddr,
    input  wire [2:0]  s_axi_arprot,
    input  wire        s_axi_arvalid,
    output wire        s_axi_arready,

    output wire [31:0] s_axi_rdata,
    output wire [1:0]  s_axi_rresp,
    output wire        s_axi_rvalid,
    input  wire        s_axi_rready
);
    localparam [1:0] AXI_OKAY   = 2'b00;
    localparam [1:0] AXI_SLVERR = 2'b10;

    localparam [7:0] REG_CTRL        = 8'h00;
    localparam [7:0] REG_UBUF_CFG    = 8'h04;
    localparam [7:0] REG_UBUF_DATA   = 8'h08;
    localparam [7:0] REG_CRD_CFG     = 8'h0c;
    localparam [7:0] REG_STATUS      = 8'h10;
    localparam [7:0] REG_CRD_DATA_LO = 8'h14;
    localparam [7:0] REG_CRD_DATA_HI = 8'h18;

    reg [31:0] ctrl_reg;
    reg [31:0] ubuf_cfg_reg;
    reg [31:0] ubuf_data_reg;
    reg [31:0] crd_cfg_reg;
    reg [63:0] crd_data_reg;
    reg        done_status;
    // 0x40 + core*32 + select_b*16 + row*4: four signed bytes,
    // least significant byte first. B is returned after the final store.
    reg [2:0] packed_left;
    reg [31:0] packed_data;
    reg [3:0] packed_strb;

    reg        aw_pending;
    reg [7:0]  awaddr_reg;
    reg        w_pending;
    reg [31:0] wdata_reg;
    reg [3:0]  wstrb_reg;
    reg        bvalid_reg;
    reg [1:0]  bresp_reg;

    reg        rvalid_reg;
    reg [31:0] rdata_reg;
    reg [1:0]  rresp_reg;

    reg        top_ubuf_wr_en;
    reg        top_start;
    reg        top_c_rd_en;
    wire       top_busy;
    wire       top_done;
    wire signed [31:0] top_c_rd_data;

    wire rst;
    assign rst = ~s_axi_aresetn;

    // AXI ready is low while a prior transaction of the same channel is
    // still being held.  The write channels remain independent of each other.
    assign s_axi_awready = ~aw_pending & ~bvalid_reg & (packed_left==0);
    assign s_axi_wready  = ~w_pending  & ~bvalid_reg & (packed_left==0);
    assign s_axi_bvalid  = bvalid_reg;
    assign s_axi_bresp   = bresp_reg;

    assign s_axi_arready = ~rvalid_reg;
    assign s_axi_rvalid  = rvalid_reg;
    assign s_axi_rdata   = rdata_reg;
    assign s_axi_rresp   = rresp_reg;

    top #(
        .NUM_CORES(2),
        .N(4),
        .DW(8),
        .CW(32),
        .NUM_BIG_CORES(2),
        .SMALL_N(4),
        .BIG_N(4)
    ) u_top (
        .clk(s_axi_aclk),
        .rst(rst),
        .ubuf_wr_en(top_ubuf_wr_en),
        .ubuf_wr_sel(ubuf_cfg_reg[0]),
        .ubuf_wr_core(ubuf_cfg_reg[8]),
        .ubuf_wr_row(ubuf_cfg_reg[17:16]),
        .ubuf_wr_col(ubuf_cfg_reg[25:24]),
        .ubuf_wr_data(ubuf_data_reg[7:0]),
        .start(top_start),
        .busy(top_busy),
        .done(top_done),
        .c_rd_en(top_c_rd_en),
        .c_rd_core(crd_cfg_reg[8]),
        .c_rd_row(crd_cfg_reg[17:16]),
        .c_rd_col(crd_cfg_reg[25:24]),
        .c_rd_data(top_c_rd_data)
    );

    function [31:0] merge_wstrb;
        input [31:0] old_value;
        input [31:0] new_value;
        input [3:0]  strobe;
        integer byte_index;
        begin
            merge_wstrb = old_value;
            for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1) begin
                if (strobe[byte_index]) begin
                    merge_wstrb[(byte_index * 8) +: 8] =
                        new_value[(byte_index * 8) +: 8];
                end
            end
        end
    endfunction

    function is_write_address;
        input [7:0] address;
        begin
            case (address)
                REG_CTRL,
                REG_UBUF_CFG,
                REG_UBUF_DATA,
                REG_CRD_CFG: is_write_address = 1'b1;
                default:     is_write_address = 1'b0;
            endcase
        end
    endfunction

    function is_read_address;
        input [7:0] address;
        begin
            case (address)
                REG_CTRL,
                REG_UBUF_CFG,
                REG_UBUF_DATA,
                REG_CRD_CFG,
                REG_STATUS,
                REG_CRD_DATA_LO,
                REG_CRD_DATA_HI: is_read_address = 1'b1;
                default:         is_read_address = 1'b0;
            endcase
        end
    endfunction

    function [31:0] read_register;
        input [7:0] address;
        begin
            case (address)
                REG_CTRL:        read_register = ctrl_reg;
                REG_UBUF_CFG:    read_register = ubuf_cfg_reg;
                REG_UBUF_DATA:   read_register = ubuf_data_reg;
                REG_CRD_CFG:     read_register = crd_cfg_reg;
                REG_STATUS:      read_register = {30'b0, (done_status | top_done),
                                                  (top_busy | top_start)};
                REG_CRD_DATA_LO: read_register = crd_data_reg[31:0];
                REG_CRD_DATA_HI: read_register = crd_data_reg[63:32];
                default:         read_register = 32'b0;
            endcase
        end
    endfunction

    always @(posedge s_axi_aclk or negedge s_axi_aresetn) begin
        if (!s_axi_aresetn) begin
            ctrl_reg      <= 32'b0;
            ubuf_cfg_reg  <= 32'b0;
            ubuf_data_reg <= 32'b0;
            crd_cfg_reg   <= 32'b0;
            crd_data_reg  <= 64'b0;
            done_status   <= 1'b0;
            packed_left <= 0;
            packed_data <= 0;
            packed_strb <= 0;

            aw_pending <= 1'b0;
            awaddr_reg <= 8'b0;
            w_pending  <= 1'b0;
            wdata_reg  <= 32'b0;
            wstrb_reg  <= 4'b0;
            bvalid_reg <= 1'b0;
            bresp_reg  <= AXI_OKAY;

            rvalid_reg <= 1'b0;
            rdata_reg  <= 32'b0;
            rresp_reg  <= AXI_OKAY;

            top_ubuf_wr_en <= 1'b0;
            top_start      <= 1'b0;
            top_c_rd_en    <= 1'b0;
        end else begin
            // All accelerator-facing controls are one-cycle pulses.
            top_ubuf_wr_en <= 1'b0;
            top_start      <= 1'b0;
            top_c_rd_en    <= 1'b0;

            if (s_axi_awvalid && s_axi_awready) begin
                aw_pending <= 1'b1;
                awaddr_reg <= s_axi_awaddr;
            end

            if (s_axi_wvalid && s_axi_wready) begin
                w_pending <= 1'b1;
                wdata_reg <= s_axi_wdata;
                wstrb_reg <= s_axi_wstrb;
            end

            // top.done is a one-cycle completion indication.  The accepted
            // idle START clear below has priority if it coincides with this
            // final observed completion pulse.
            if (top_done) begin
                done_status <= 1'b1;
            end

            // Commit exactly once, after independently latched AW and W.
            if (packed_left!=0) begin
                packed_left <= packed_left-1'b1;
                if (packed_left==1) begin
                    bvalid_reg <= 1'b1;
                end else begin
                    ubuf_cfg_reg[25:24] <= ubuf_cfg_reg[25:24]+1'b1;
                    ubuf_data_reg <= {24'b0,packed_data[7:0]};
                    top_ubuf_wr_en <= packed_strb[0];
                    packed_data <= {8'b0,packed_data[31:8]};
                    packed_strb <= {1'b0,packed_strb[3:1]};
                end
            end
            if (aw_pending && w_pending && !bvalid_reg && packed_left==0) begin
                aw_pending <= 1'b0;
                w_pending  <= 1'b0;
                bvalid_reg <= 1'b1;

                if (awaddr_reg[7:6]==2'b01 && awaddr_reg[1:0]==0) begin
                    bresp_reg <= AXI_SLVERR;
                    if (!top_busy && !top_start) begin
                        bvalid_reg <= 1'b0;
                        bresp_reg <= AXI_OKAY;
                        ubuf_cfg_reg <= {14'b0,awaddr_reg[3:2],7'b0,awaddr_reg[5],7'b0,awaddr_reg[4]};
                        ubuf_data_reg <= {24'b0,wdata_reg[7:0]};
                        top_ubuf_wr_en <= wstrb_reg[0];
                        packed_data <= {8'b0,wdata_reg[31:8]};
                        packed_strb <= {1'b0,wstrb_reg[3:1]};
                        packed_left <= 4;
                    end
                end else if (is_write_address(awaddr_reg)) begin
                    bresp_reg <= AXI_OKAY;
                    case (awaddr_reg)
                        REG_CTRL: begin
                            ctrl_reg <= merge_wstrb(ctrl_reg, wdata_reg, wstrb_reg);
                            // top_start is emitted below for every accepted
                            // START write.  It will be consumed by top on the
                            // following clock.  top_busy is sampled here,
                            // before that pulse is launched, so a START
                            // written while busy cannot clear DONE.
                            if (wstrb_reg[0] && wdata_reg[0] && !top_busy) begin
                                done_status <= 1'b0;
                            end
                            if (wstrb_reg[0] && wdata_reg[0]) begin
                                top_start <= 1'b1;
                            end
                            if (wstrb_reg[0] && wdata_reg[1]) begin
                                top_ubuf_wr_en <= 1'b1;
                            end
                            if (wstrb_reg[0] && wdata_reg[2]) begin
                                top_c_rd_en <= 1'b1;
                            end
                        end
                        REG_UBUF_CFG: begin
                            ubuf_cfg_reg <= merge_wstrb(
                                ubuf_cfg_reg, wdata_reg, wstrb_reg);
                        end
                        REG_UBUF_DATA: begin
                            ubuf_data_reg <= merge_wstrb(
                                ubuf_data_reg, wdata_reg, wstrb_reg);
                        end
                        REG_CRD_CFG: begin
                            crd_cfg_reg <= merge_wstrb(
                                crd_cfg_reg, wdata_reg, wstrb_reg);
                        end
                        default: begin
                            // is_write_address excludes this case.
                        end
                    endcase
                end else begin
                    // Status and result registers are read-only; all other
                    // offsets are unmapped and return the same AXI error.
                    bresp_reg <= AXI_SLVERR;
                end
            end

            if (bvalid_reg && s_axi_bready) begin
                bvalid_reg <= 1'b0;
            end

            // Capture one cycle after the CRD read pulse becomes visible to
            // top.  top_c_rd_data is the selected 32-bit signed C value.
            if (top_c_rd_en) begin
                crd_data_reg <= {{32{top_c_rd_data[31]}}, top_c_rd_data};
            end

            if (s_axi_arvalid && s_axi_arready) begin
                rvalid_reg <= 1'b1;
                if (is_read_address(s_axi_araddr)) begin
                    rresp_reg <= AXI_OKAY;
                    rdata_reg <= read_register(s_axi_araddr);
                end else begin
                    rresp_reg <= AXI_SLVERR;
                    rdata_reg <= 32'b0;
                end
            end

            if (rvalid_reg && s_axi_rready) begin
                rvalid_reg <= 1'b0;
            end
        end
    end
endmodule
