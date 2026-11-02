`timescale 1ns/1ps

// Fixed FPGA-facing AXI4-Lite wrapper for the eight-core 4x4 accelerator.
//
// The AXI channels are deliberately handled independently: AW and W may be
// presented in either order and are committed as one write only after both
// have been accepted.  There is one outstanding write response and one
// outstanding read response.
module tiny3tpu_axi (
    input  wire        s_axi_aclk,
    input  wire        s_axi_aresetn,

    input  wire [9:0]  s_axi_awaddr,
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

    input  wire [9:0]  s_axi_araddr,
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

    localparam [9:0] REG_CTRL        = 10'h000;
    localparam [9:0] REG_UBUF_CFG    = 10'h004;
    localparam [9:0] REG_UBUF_DATA   = 10'h008;
    localparam [9:0] REG_CRD_CFG     = 10'h00c;
    localparam [9:0] REG_STATUS      = 10'h010;
    localparam [9:0] REG_CRD_DATA_LO = 10'h014;
    localparam [9:0] REG_CRD_DATA_HI = 10'h018;
    localparam [9:0] REG_RESULT_BASE = 10'h200;

    reg [31:0] ctrl_reg;
    reg [31:0] ubuf_cfg_reg;
    reg [31:0] ubuf_data_reg;
    reg [31:0] crd_cfg_reg;
    reg [63:0] crd_data_reg;
    reg        done_status;
    // 0x040 + core*32 + select_b*16 + row*4 (and broadcast apertures at
    // 0x020..0x03c and 0x140..0x1fc): four signed bytes committed in parallel.
    reg [2:0]  packed_left;
    reg [31:0] packed_data;
    reg [3:0]  packed_strb;
    reg [7:0]  packed_mask;
    reg [7:0]  top_ubuf_wr_mask;
    reg [3:0]  top_ubuf_wr_row_strb;
    reg [31:0] top_ubuf_wr_row_data;

    reg        aw_pending;
    reg [9:0]  awaddr_reg;
    reg        w_pending;
    reg [31:0] wdata_reg;
    reg [3:0]  wstrb_reg;
    reg        bvalid_reg;
    reg [1:0]  bresp_reg;

    reg        rvalid_reg;
    reg [31:0] rdata_reg;
    reg [1:0]  rresp_reg;
    reg        result_window_pending;
    reg        result_window_lock;
    reg [2:0]  result_window_core;
    reg [1:0]  result_window_row;
    reg [1:0]  result_window_col;

    reg        top_ubuf_wr_en;
    reg        top_start;
    reg        top_continue_accum;
    reg        top_c_rd_en;
    wire       top_busy;
    wire       top_done;
    wire signed [31:0] top_c_rd_data;
    wire [9:0] window_addr_offset = s_axi_araddr - REG_RESULT_BASE;
    // Only arbitrate writes against a direct read that can actually be
    // accepted now. An unrelated stalled R response must not block writes.
    wire       window_read_request = s_axi_arvalid && !rvalid_reg &&
                                    !result_window_lock &&
                                    is_result_window_address(s_axi_araddr);
    wire       write_inflight = aw_pending || w_pending || bvalid_reg ||
                                (packed_left != 0);

    wire rst;
    assign rst = ~s_axi_aresetn;

    // AXI ready is low while a prior transaction of the same channel is
    // still being held.  The write channels remain independent of each other.
    // A window read takes priority over a new write, but must not strand a
    // write half that was accepted before ARVALID. Let its missing partner
    // through, then wait for the write response to drain before accepting AR.
    assign s_axi_awready = ~aw_pending & ~bvalid_reg & (packed_left==0) &
                           ~result_window_lock &
                           (~window_read_request | w_pending);
    assign s_axi_wready  = ~w_pending  & ~bvalid_reg & (packed_left==0) &
                           ~result_window_lock &
                           (~window_read_request | aw_pending);
    assign s_axi_bvalid  = bvalid_reg;
    assign s_axi_bresp   = bresp_reg;

    assign s_axi_arready = ~rvalid_reg & ~result_window_lock &
                           (~window_read_request | ~write_inflight);
    assign s_axi_rvalid  = rvalid_reg;
    assign s_axi_rdata   = rdata_reg;
    assign s_axi_rresp   = rresp_reg;

    top #(
        .NUM_CORES(8),
        .N(4),
        .DW(8),
        .CW(32),
        .NUM_BIG_CORES(8),
        .SMALL_N(4),
        .BIG_N(4)
    ) u_top (
        .clk(s_axi_aclk),
        .rst(rst),
        .ubuf_wr_en(top_ubuf_wr_en),
        .ubuf_wr_sel(ubuf_cfg_reg[0]),
        .ubuf_wr_core(ubuf_cfg_reg[10:8]),
        .ubuf_wr_mask(top_ubuf_wr_mask),
        .ubuf_wr_row(ubuf_cfg_reg[17:16]),
        .ubuf_wr_col(ubuf_cfg_reg[25:24]),
        .ubuf_wr_data(ubuf_data_reg[7:0]),
        .ubuf_wr_row_strb(top_ubuf_wr_row_strb),
        .ubuf_wr_row_data(top_ubuf_wr_row_data),
        .start(top_start),
        .continue_accum(top_continue_accum),
        .busy(top_busy),
        .done(top_done),
        .c_rd_en(top_c_rd_en),
        .c_rd_core(result_window_pending ? result_window_core : crd_cfg_reg[10:8]),
        .c_rd_row(result_window_pending ? result_window_row : crd_cfg_reg[17:16]),
        .c_rd_col(result_window_pending ? result_window_col : crd_cfg_reg[25:24]),
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
        input [9:0] address;
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
        input [9:0] address;
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

    function is_packed_write_address;
        input [9:0] address;
        begin
            is_packed_write_address = (address >= 10'h020) &&
                                      (address < 10'h200) &&
                                      (address[1:0] == 2'b00);
        end
    endfunction

    function [7:0] decode_packed_mask;
        input [9:0] address;
        reg [2:0] core_idx;
        reg [3:0] group_idx;
        begin
            if (address < 10'h040) begin
                decode_packed_mask = address[4] ? 8'haa : 8'h55;
            end else if (address < 10'h140) begin
                core_idx = (address - 10'h040) >> 5;
                decode_packed_mask = 8'd1 << core_idx;
            end else begin
                group_idx = (address - 10'h140) >> 4;
                case (group_idx)
                    4'd0:    decode_packed_mask = 8'hff;
                    4'd1:    decode_packed_mask = 8'hff;
                    4'd2:    decode_packed_mask = 8'h0f;
                    4'd3:    decode_packed_mask = 8'hf0;
                    4'd4:    decode_packed_mask = 8'h11;
                    4'd5:    decode_packed_mask = 8'h22;
                    4'd6:    decode_packed_mask = 8'h44;
                    4'd7:    decode_packed_mask = 8'h88;
                    4'd8:    decode_packed_mask = 8'h03;
                    4'd9:    decode_packed_mask = 8'h0c;
                    4'd10:   decode_packed_mask = 8'h30;
                    4'd11:   decode_packed_mask = 8'hc0;
                    default: decode_packed_mask = 8'h00;
                endcase
            end
        end
    endfunction

    function decode_packed_select_b;
        input [9:0] address;
        reg [3:0] group_idx;
        begin
            if (address < 10'h040) begin
                decode_packed_select_b = 1'b1;
            end else if (address < 10'h140) begin
                decode_packed_select_b = address[4];
            end else begin
                group_idx = (address - 10'h140) >> 4;
                decode_packed_select_b = (group_idx == 4'd1) ||
                                         (group_idx >= 4'd4 && group_idx <= 4'd7);
            end
        end
    endfunction

    function [2:0] decode_packed_core;
        input [9:0] address;
        reg [3:0] group_idx;
        begin
            if (address < 10'h040) begin
                decode_packed_core = {2'b00, address[4]};
            end else if (address < 10'h140) begin
                decode_packed_core = (address - 10'h040) >> 5;
            end else begin
                group_idx = (address - 10'h140) >> 4;
                case (group_idx)
                    4'd3:    decode_packed_core = 3'd4;
                    4'd5:    decode_packed_core = 3'd1;
                    4'd6:    decode_packed_core = 3'd2;
                    4'd7:    decode_packed_core = 3'd3;
                    4'd9:    decode_packed_core = 3'd2;
                    4'd10:   decode_packed_core = 3'd4;
                    4'd11:   decode_packed_core = 3'd6;
                    default: decode_packed_core = 3'd0;
                endcase
            end
        end
    endfunction

    function is_result_window_address;
        input [9:0] address;
        begin
            is_result_window_address = (address >= REG_RESULT_BASE) &&
                                      (address <= 10'h3fc) &&
                                      (address[1:0] == 2'b00);
        end
    endfunction

    function [31:0] read_register;
        input [9:0] address;
        begin
            case (address)
                REG_CTRL:        read_register = ctrl_reg;
                REG_UBUF_CFG:    read_register = ubuf_cfg_reg;
                REG_UBUF_DATA:   read_register = ubuf_data_reg;
                REG_CRD_CFG:     read_register = crd_cfg_reg;
                // Bits 8 and 9 advertise accumulation and direct-result
                // window support. Keep legacy BUSY/DONE positions at bits
                // 0/1; the other upper bits remain zero.
                REG_STATUS:      read_register = {22'b0, 1'b1, 1'b1, 6'b0,
                                                  (done_status | top_done),
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
            packed_left   <= 3'd0;
            packed_data   <= 32'b0;
            packed_strb   <= 4'b0;
            packed_mask   <= 8'b0;
            top_ubuf_wr_mask <= 8'b0;
            top_ubuf_wr_row_strb <= 4'b0;
            top_ubuf_wr_row_data <= 32'b0;

            aw_pending <= 1'b0;
            awaddr_reg <= 10'b0;
            w_pending  <= 1'b0;
            wdata_reg  <= 32'b0;
            wstrb_reg  <= 4'b0;
            bvalid_reg <= 1'b0;
            bresp_reg  <= AXI_OKAY;

            rvalid_reg <= 1'b0;
            rdata_reg  <= 32'b0;
            rresp_reg  <= AXI_OKAY;
            result_window_pending <= 1'b0;
            result_window_lock <= 1'b0;
            result_window_core <= 3'b0;
            result_window_row <= 2'b0;
            result_window_col <= 2'b0;

            top_ubuf_wr_en <= 1'b0;
            top_start      <= 1'b0;
            top_continue_accum <= 1'b0;
            top_c_rd_en    <= 1'b0;
        end else begin
            // All accelerator-facing controls are one-cycle pulses.
            top_ubuf_wr_en <= 1'b0;
            top_ubuf_wr_mask <= 8'b0;
            top_ubuf_wr_row_strb <= 4'b0;
            top_ubuf_wr_row_data <= 32'b0;
            top_start      <= 1'b0;
            top_continue_accum <= 1'b0;
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
                    top_ubuf_wr_mask <= packed_mask;
                    packed_data <= {8'b0,packed_data[31:8]};
                    packed_strb <= {1'b0,packed_strb[3:1]};
                end
            end
            if (aw_pending && w_pending && !bvalid_reg && packed_left==0) begin
                aw_pending <= 1'b0;
                w_pending  <= 1'b0;
                bvalid_reg <= 1'b1;

                if (is_packed_write_address(awaddr_reg)) begin
                    bresp_reg <= AXI_SLVERR;
                    if (!top_busy && !top_start) begin
                        bresp_reg <= AXI_OKAY;
                        ubuf_cfg_reg <= {6'b0, 2'd3, 6'b0, awaddr_reg[3:2], 5'b0,
                                         decode_packed_core(awaddr_reg),
                                         7'b0, decode_packed_select_b(awaddr_reg)};
                        ubuf_data_reg <= {24'b0, wdata_reg[31:24]};
                        top_ubuf_wr_en <= |wstrb_reg;
                        top_ubuf_wr_mask <= decode_packed_mask(awaddr_reg);
                        top_ubuf_wr_row_strb <= wstrb_reg;
                        top_ubuf_wr_row_data <= wdata_reg;
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
                                top_continue_accum <= wdata_reg[3];
                            end
                            if (wstrb_reg[0] && wdata_reg[1]) begin
                                top_ubuf_wr_en <= 1'b1;
                                top_ubuf_wr_mask <= 8'b0;
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
            if (top_c_rd_en && !result_window_pending) begin
                crd_data_reg <= {{32{top_c_rd_data[31]}}, top_c_rd_data};
            end

            // Reuse the existing combinational top C-data mux. The selector
            // is latched through this cycle; capture before releasing the
            // short selector lock. RDATA is now registered, so writes may
            // proceed during an arbitrary R-channel stall.
            if (result_window_pending) begin
                result_window_pending <= 1'b0;
                result_window_lock <= 1'b0;
                rvalid_reg <= 1'b1;
                rresp_reg <= AXI_OKAY;
                rdata_reg <= top_c_rd_data;
            end

            if (s_axi_arvalid && s_axi_arready) begin
                if (is_result_window_address(s_axi_araddr)) begin
                    if (top_busy || top_start) begin
                        rvalid_reg <= 1'b1;
                        rresp_reg <= AXI_SLVERR;
                        rdata_reg <= 32'b0;
                    end else begin
                        result_window_core <= window_addr_offset[8:6];
                        result_window_row <= window_addr_offset[5:4];
                        result_window_col <= window_addr_offset[3:2];
                        result_window_pending <= 1'b1;
                        result_window_lock <= 1'b1;
                        top_c_rd_en <= 1'b1;
                    end
                end else if (is_read_address(s_axi_araddr)) begin
                    rvalid_reg <= 1'b1;
                    rresp_reg <= AXI_OKAY;
                    rdata_reg <= read_register(s_axi_araddr);
                end else begin
                    rvalid_reg <= 1'b1;
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
