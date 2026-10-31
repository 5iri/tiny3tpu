`timescale 1ns/1ps
`default_nettype none
// VexRiscv Lite: cached instruction bus, uncached data bus, one system clock.
// Each Wishbone beat is captured before decoding and gets exactly one registered
// response. Arbitration is round robin between beats, including cache refills.
module vexriscv_tpu_soc #(
    parameter BOOT_HEX = "",
    parameter BOOT_WORDS = 16384,
    parameter PIPELINED_DECODE = 0,
    parameter ENABLE_CORDIC = 0,
    parameter ENABLE_FPU = 1,
    // Explicit hardware/firmware ABI choice. Legacy bitstreams use the mailbox.
    parameter DIRECT_TPU = 0
) (
    input wire clk, input wire rst, input wire ready_to_run,
    input wire uart_rx, output wire uart_tx,
    output reg fault, output wire [31:0] pc_debug,
    output wire ext_req_valid, input wire ext_req_ready,
    output wire ext_req_write, output wire [31:0] ext_req_addr,
    output wire [31:0] ext_req_wdata, output wire [3:0] ext_req_wstrb,
    input wire ext_resp_valid, output wire ext_resp_ready,
    input wire [31:0] ext_resp_rdata, input wire ext_resp_error,
    output reg report_valid, output reg [31:0] report_data,
    output reg exit_valid, output reg [31:0] exit_code
);
    wire i_cyc, i_stb, d_cyc, d_stb, d_we;
    wire [29:0] i_adr, d_adr;
    wire [31:0] d_wdata;
    wire [3:0] d_sel;
    wire [31:0] bus_rdata;
    reg [31:0] response_data;
    reg response_error;
    reg [3:0] termination;
    reg owner_data, last_owner_data;
    localparam IDLE=3'd0, LOCAL=3'd1, EXT_REQ=3'd2, EXT_WAIT=3'd3, RESP=3'd4, DECODE=3'd5,
               TPU_REQ=3'd6, TPU_WAIT=3'd7;
    reg [2:0] state;
    // Register each master's ACK/ERR separately. Do not decode state, owner,
    // error or the board reset combinationally into the CPU's control path.
    // Local reset register cuts the board-wide reset fanout out of the CPU's
    // synchronous control paths. The bus stays idle while the core is reset.
    reg cpu_reset = 1'b1;
    always @(posedge clk) cpu_reset <= rst || !ready_to_run;
    reg peripheral_reset = 1'b1;
    always @(posedge clk) peripheral_reset <= rst;
    VexRiscv cpu (
        .clk(clk), .reset(cpu_reset), .externalResetVector(32'h80000000),
        .timerInterrupt(1'b0), .softwareInterrupt(1'b0), .externalInterruptArray(32'b0),
        .iBusWishbone_CYC(i_cyc), .iBusWishbone_STB(i_stb),
        .iBusWishbone_ADR(i_adr), .iBusWishbone_WE(), .iBusWishbone_SEL(),
        .iBusWishbone_DAT_MOSI(), .iBusWishbone_DAT_MISO(bus_rdata),
        .iBusWishbone_ACK(termination[0]),
        .iBusWishbone_ERR(termination[1]),
        .iBusWishbone_CTI(), .iBusWishbone_BTE(),
        .dBusWishbone_CYC(d_cyc), .dBusWishbone_STB(d_stb),
        .dBusWishbone_ADR(d_adr), .dBusWishbone_WE(d_we), .dBusWishbone_SEL(d_sel),
        .dBusWishbone_DAT_MOSI(d_wdata), .dBusWishbone_DAT_MISO(bus_rdata),
        .dBusWishbone_ACK(termination[2]),
        .dBusWishbone_ERR(termination[3]),
        .dBusWishbone_CTI(), .dBusWishbone_BTE()
    );
    // Fetch address for diagnostics (cache-line refill address, not retired PC).
    assign pc_debug = {i_adr, 2'b00};
    wire i_pending = i_cyc && i_stb;
    wire d_pending = d_cyc && d_stb;
    wire select_data = d_pending && (!i_pending || !last_owner_data);
    reg [31:0] addr, wdata;
    reg [3:0] wstrb;
    reg write;
    wire [5:0] address_decode = {
        addr == 32'h20002004,
        addr == 32'h20002000,
        DIRECT_TPU ? addr[31:10] == (32'h20001000 >> 10) : addr[31:5] == (32'h20001000 >> 5),
        addr[31:5] == (32'h20000000 >> 5),
        addr >= 32'h80000000 && (addr - 32'h80000000) < BOOT_WORDS*4,
        addr[31:30] == 2'b01 || addr[31:16] == 16'hf000
    };
    reg [5:0] registered_decode;
    reg registered_full_write;
    // The larger DDR design spreads peripherals across the device. Register
    // window selection before applying peripheral side effects to cut the wide
    // address comparator out of UART/mailbox enables and the response mux.
    wire [5:0] selected_address = PIPELINED_DECODE ? registered_decode : address_decode;
    wire external_address = selected_address[0];
    wire boot_address = selected_address[1];
    wire uart_address = selected_address[2];
    wire tpu_address = selected_address[3];
    wire full_write = PIPELINED_DECODE ? registered_full_write : (write && wstrb == 15);
    wire report_write = selected_address[5] && full_write;
    wire exit_write = selected_address[4] && full_write;
    wire timer_address = addr == 32'h20002008;
    reg [31:0] system_cycles = 0;
    always @(posedge clk) begin
        if (rst) system_cycles <= 0;
        else system_cycles <= system_cycles + 1'b1;
    end
    wire cordic_address = ENABLE_CORDIC && addr[31:4] == (32'h20003000 >> 4);
    wire [31:0] cordic_data;
    generate if(ENABLE_CORDIC)begin: math_peripheral
      tiny3tpu_cordic_mmio cordic(.clk(clk),.rst(peripheral_reset),
        .wr(local_access && cordic_address && full_write),.addr(addr[3:0]),
        .wdata(wdata),.wstrb(wstrb),.rdata(cordic_data));
    end else begin assign cordic_data=0;end endgenerate
    wire fpu_address = ENABLE_FPU && addr[31:6] == (32'h20003040 >> 6);
    wire [31:0] fpu_data;
    generate if(ENABLE_FPU)begin: fpu_peripheral
      tiny3tpu_fpu_mmio fpu(.clk(clk),.rst(peripheral_reset),
        .wr(local_access && fpu_address && full_write),.addr(addr[5:0]),
        .wdata(wdata),.wstrb(wstrb),.rdata(fpu_data));
    end else begin assign fpu_data=0;end endgenerate
    wire local_error = !(boot_address || tpu_address || timer_address || (cordic_address && (!write || full_write)) ||
                         (fpu_address && (!write || full_write)) ||
                         (uart_address && (!write || full_write)) || report_write || exit_write);
    function [3:0] terminate_beat;
        input data_owner, error;
        begin
            terminate_beat = {data_owner && error, data_owner && !error,
                              !data_owner && error, !data_owner && !error};
        end
    endfunction
    // Peripheral reset already dominates writes/reads. Do not route the global
    // reset through their command decode as well as their reset pins.
    wire local_access = state == LOCAL;
    assign ext_req_valid = state == EXT_REQ && !rst;
    assign ext_req_write = write;
    assign ext_req_addr = addr;
    assign ext_req_wdata = wdata;
    assign ext_req_wstrb = wstrb;
    assign ext_resp_ready = state == EXT_WAIT && !rst;

    reg [31:0] boot_mem [0:BOOT_WORDS-1];
    initial if (BOOT_HEX != "") $readmemh(BOOT_HEX, boot_mem);
    wire [$clog2(BOOT_WORDS)-1:0] boot_index = addr[$clog2(BOOT_WORDS)+1:2];
    reg [31:0] boot_rdata;
    reg response_boot;
    // Separate synchronous BRAM output register; no reset on memory/read data.
    assign bus_rdata = response_boot ? boot_rdata : response_data;
    // The CPU response mux uses this registered RAM read just like peripheral data.
    wire [31:0] tpu_data, uart_data;
    wire tpu_req_ready,tpu_resp_valid,tpu_resp_error;
    wire [31:0] tpu_resp_data;
    generate if(DIRECT_TPU)begin: direct_tpu
      tiny3tpu_direct_peripheral accelerator (
        .clk(clk),.rst_n(!peripheral_reset),
        .req_valid(state==TPU_REQ),.req_ready(tpu_req_ready),
        .req_write(write),.req_addr(addr[9:0]),.req_wdata(wdata),.req_wstrb(wstrb),
        .resp_valid(tpu_resp_valid),.resp_ready(state==TPU_WAIT),
        .resp_rdata(tpu_resp_data),.resp_error(tpu_resp_error)
      );
      assign tpu_data=0;
    end else begin: mailbox_tpu
      synapse32_tpu_peripheral accelerator (
        .clk(clk), .rst_n(!peripheral_reset), .cpu_wr_en(local_access && tpu_address && write),
        .cpu_rd_en(local_access && tpu_address && !write), .cpu_addr(addr[4:0]),
        .cpu_wdata(wdata), .cpu_wstrb(wstrb), .cpu_rdata(tpu_data)
      );
      assign tpu_req_ready=0;
      assign tpu_resp_valid=0;
      assign tpu_resp_error=0;
      assign tpu_resp_data=0;
    end endgenerate
    // High address bits have already been decoded. Keeping them constant avoids
    // carrying the UART's legacy 32-bit range comparator through its read path.
    // The USB UART is asynchronous to clk. Only the second synchronizer
    // register may feed the receiver's edge detector and sampling logic.
    (* ASYNC_REG = "TRUE" *) reg [1:0] uart_rx_sync = 2'b11;
    always @(posedge clk) begin
        if (peripheral_reset) uart_rx_sync <= 2'b11;
        else uart_rx_sync <= {uart_rx_sync[0], uart_rx};
    end
    uart serial (
        .clk(clk), .rst(peripheral_reset), .addr({27'h1000000, addr[4:0]}), .write_data(wdata),
        .write_enable(local_access && uart_address && full_write),
        .read_enable(local_access && uart_address && !write),
        .read_data(uart_data), .uart_valid(), .interrupt(), .tx(uart_tx), .rx(uart_rx_sync[1])
    );
    integer lane;
    always @(posedge clk) begin
        if (local_access && boot_address && !rst) begin
            boot_rdata <= boot_mem[boot_index];
            for (lane=0; lane<4; lane=lane+1)
                if (write && wstrb[lane]) boot_mem[boot_index][lane*8 +: 8] <= wdata[lane*8 +: 8];
        end
        if (rst) begin
            state <= IDLE; owner_data <= 0; last_owner_data <= 1;
            addr <= 0; wdata <= 0; wstrb <= 0; write <= 0;
            response_data <= 0; response_error <= 0; response_boot <= 0;
            termination <= 0;
            fault <= 0; report_valid <= 0; report_data <= 0; exit_valid <= 0; exit_code <= 0;
        end else begin
            report_valid <= 0; exit_valid <= 0;
            termination <= 0;
            case (state)
                IDLE: if (ready_to_run && (i_pending || d_pending)) begin
                    owner_data <= select_data; last_owner_data <= select_data;
                    addr <= {select_data ? d_adr : i_adr, 2'b00};
                    wdata <= d_wdata; wstrb <= select_data ? d_sel : 4'hf;
                    write <= select_data && d_we;
                    response_error <= 0; response_boot <= 0;
                    state <= PIPELINED_DECODE ? DECODE : LOCAL;
                end
                DECODE: begin
                    registered_decode <= address_decode;
                    registered_full_write <= write && wstrb == 15;
                    state <= LOCAL;
                end
                LOCAL: begin
                    if (external_address) state <= EXT_REQ;
                    else if (DIRECT_TPU && tpu_address) state <= TPU_REQ;
                    else begin
                        state <= RESP; response_data <= 0;
                        response_boot <= boot_address;
                        response_error <= local_error;
                        termination <= terminate_beat(owner_data, local_error);
                        if (boot_address) begin end
                        else if (timer_address) response_data <= system_cycles;
                        else if (tpu_address) response_data <= tpu_data;
                        else if (cordic_address) response_data <= cordic_data;
                        else if (fpu_address) response_data <= fpu_data;
                        else if (uart_address) begin
                            response_data <= uart_data;
                        end else if (report_write) begin
                            report_valid <= 1; report_data <= wdata;
                        end else if (exit_write) begin
                            exit_valid <= 1; exit_code <= wdata;
                        end
                    end
                end
                EXT_REQ: if (ext_req_ready) state <= EXT_WAIT;
                TPU_REQ: if(tpu_req_ready)state<=TPU_WAIT;
                TPU_WAIT: if(tpu_resp_valid)begin
                    response_data<=tpu_resp_data;response_error<=tpu_resp_error;
                    termination<=terminate_beat(owner_data,tpu_resp_error);
                    state<=RESP;
                end
                EXT_WAIT: if (ext_resp_valid) begin
                    response_data <= ext_resp_rdata; response_error <= ext_resp_error;
                    termination <= terminate_beat(owner_data, ext_resp_error);
                    state <= RESP;
                end
                RESP: begin
                    if (response_error) fault <= 1;
                    // The CPU consumes ACK on this edge and updates its next
                    // address. Only capture again on the following IDLE edge.
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule

`ifndef TINY3TPU_FPU_MMIO_SV
`define TINY3TPU_FPU_MMIO_SV
module tiny3tpu_fpu_mmio(
    input wire clk,
    input wire rst,
    input wire wr,
    input wire [5:0] addr,
    input wire [31:0] wdata,
    input wire [3:0] wstrb,
    output reg [31:0] rdata
);
    reg [31:0] opa, opb;

    always @(posedge clk) begin
        if (rst) begin
            opa <= 32'd0;
            opb <= 32'd0;
        end else if (wr && wstrb == 4'hf) begin
            if (addr == 6'h00) opa <= wdata;
            else if (addr == 6'h04) opb <= wdata;
        end
    end

    function automatic [5:0] clz32(input [31:0] v);
        integer k;
        reg found;
        begin
            clz32 = 6'd32;
            found = 1'b0;
            for (k = 31; k >= 0; k = k - 1) begin
                if (!found && v[k]) begin
                    clz32 = 6'd31 - k[5:0];
                    found = 1'b1;
                end
            end
        end
    endfunction

    function automatic [4:0] clz24(input [23:0] v);
        integer k;
        reg found;
        begin
            clz24 = 5'd24;
            found = 1'b0;
            for (k = 23; k >= 0; k = k - 1) begin
                if (!found && v[k]) begin
                    clz24 = 5'd23 - k[4:0];
                    found = 1'b1;
                end
            end
        end
    endfunction

    function automatic [4:0] clz27(input [26:0] v);
        integer k;
        reg found;
        begin
            clz27 = 5'd27;
            found = 1'b0;
            for (k = 26; k >= 0; k = k - 1) begin
                if (!found && v[k]) begin
                    clz27 = 5'd26 - k[4:0];
                    found = 1'b1;
                end
            end
        end
    endfunction

    function automatic [31:0] int_to_f32(input [31:0] x, input is_signed);
        reg sign;
        reg [31:0] mag;
        reg [5:0] lz;
        reg [31:0] norm;
        reg [7:0] exp;
        reg [22:0] mant;
        reg round_bit, sticky_bit, inc;
        reg [23:0] rounded;
        begin
            if (x == 32'd0) begin
                int_to_f32 = 32'd0;
            end else begin
                sign = is_signed && x[31];
                mag = sign ? (32'd0 - x) : x;
                lz = clz32(mag);
                norm = mag << lz;
                exp = 8'd158 - {2'b00, lz};
                mant = norm[30:8];
                round_bit = norm[7];
                sticky_bit = |norm[6:0];
                inc = round_bit & (sticky_bit | mant[0]);
                rounded = {1'b0, mant} + {23'd0, inc};
                int_to_f32 = {sign, exp + {7'd0, rounded[23]}, rounded[22:0]};
            end
        end
    endfunction

    function automatic [31:0] f32_to_i32(input [31:0] x);
        reg sign;
        reg [30:0] ax;
        reg [7:0] exp;
        reg [31:0] mag;
        begin
            sign = x[31];
            ax = x[30:0];
            if (ax < 31'h3f800000 || ax > 31'h7f800000) begin
                f32_to_i32 = 32'd0;
            end else if (ax >= 31'h4f000000) begin
                f32_to_i32 = sign ? 32'h80000000 : 32'h7fffffff;
            end else begin
                exp = ax[30:23] - 8'd127;
                mag = {8'd0, 1'b1, ax[22:0]};
                if (exp >= 8'd23) mag = mag << (exp - 8'd23);
                else mag = mag >> (8'd23 - exp);
                f32_to_i32 = sign ? (32'd0 - mag) : mag;
            end
        end
    endfunction

    function automatic [31:0] f32_to_u32(input [31:0] x);
        reg sign;
        reg [30:0] ax;
        reg [7:0] exp;
        reg [31:0] mag;
        begin
            sign = x[31];
            ax = x[30:0];
            if (sign || ax < 31'h3f800000 || ax > 31'h7f800000) begin
                f32_to_u32 = 32'd0;
            end else if (ax >= 31'h4f800000) begin
                f32_to_u32 = 32'hffffffff;
            end else begin
                exp = ax[30:23] - 8'd127;
                mag = {8'd0, 1'b1, ax[22:0]};
                if (exp >= 8'd23) mag = mag << (exp - 8'd23);
                else mag = mag >> (8'd23 - exp);
                f32_to_u32 = mag;
            end
        end
    endfunction

    function automatic [31:0] f32_to_i8(input [31:0] x);
        reg sign;
        reg [30:0] ax;
        reg [31:0] mag;
        reg [31:0] signed_val;
        begin
            sign = x[31];
            ax = x[30:0];
            if (ax < 31'h3f800000 || ax > 31'h7f800000) begin
                f32_to_i8 = 32'd0;
            end else if (!sign && ax >= 31'h42fe0000) begin
                f32_to_i8 = 32'd127;
            end else if (sign && ax >= 31'h43000000) begin
                f32_to_i8 = 32'hffffff80;
            end else begin
                mag = ({8'd0, 1'b1, ax[22:0]}) >> (8'd150 - ax[30:23]);
                signed_val = sign ? (32'd0 - mag) : mag;
                f32_to_i8 = {{24{signed_val[7]}}, signed_val[7:0]};
            end
        end
    endfunction

    function automatic [31:0] f32_to_u8(input [31:0] x);
        reg sign;
        reg [30:0] ax;
        reg [31:0] mag;
        begin
            sign = x[31];
            ax = x[30:0];
            if (sign || ax < 31'h3f800000 || ax > 31'h7f800000) begin
                f32_to_u8 = 32'd0;
            end else if (ax >= 31'h437f0000) begin
                f32_to_u8 = 32'd255;
            end else begin
                mag = ({8'd0, 1'b1, ax[22:0]}) >> (8'd150 - ax[30:23]);
                f32_to_u8 = {24'd0, mag[7:0]};
            end
        end
    endfunction

    function automatic [31:0] f32_add(input [31:0] a, input [31:0] b);
        reg sa, sb, s_big, s_small;
        reg [7:0] ea, eb, e_big, e_small;
        reg [22:0] fa, fb, f_big, f_small;
        reg a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        reg swap;
        reg [8:0] exp_big, exp_small, diff, exp_norm, max_shift;
        reg [26:0] sig_big, sig_small_raw, sig_small, norm;
        reg [53:0] wide_shift;
        reg [27:0] sum;
        reg [26:0] diff_sig;
        reg [4:0] lzc;
        reg [22:0] mant;
        reg g, r, s, inc;
        reg [23:0] rounded;
        reg [8:0] final_exp;
        begin
            sa = a[31]; ea = a[30:23]; fa = a[22:0];
            sb = b[31]; eb = b[30:23]; fb = b[22:0];
            a_nan = (ea == 8'hff) && (fa != 23'd0);
            b_nan = (eb == 8'hff) && (fb != 23'd0);
            a_inf = (ea == 8'hff) && (fa == 23'd0);
            b_inf = (eb == 8'hff) && (fb == 23'd0);
            a_zero = (ea == 8'd0) && (fa == 23'd0);
            b_zero = (eb == 8'd0) && (fb == 23'd0);

            if (a_nan || b_nan) begin
                f32_add = 32'h7fc00000;
            end else if (a_inf && b_inf) begin
                f32_add = (sa != sb) ? 32'h7fc00000 : {sa, 8'hff, 23'd0};
            end else if (a_inf) begin
                f32_add = {sa, 8'hff, 23'd0};
            end else if (b_inf) begin
                f32_add = {sb, 8'hff, 23'd0};
            end else if (a_zero && b_zero) begin
                f32_add = {sa & sb, 31'd0};
            end else if (a_zero) begin
                f32_add = b;
            end else if (b_zero) begin
                f32_add = a;
            end else begin
                swap = ({eb, fb} > {ea, fa});
                s_big = swap ? sb : sa;
                e_big = swap ? eb : ea;
                f_big = swap ? fb : fa;
                s_small = swap ? sa : sb;
                e_small = swap ? ea : eb;
                f_small = swap ? fa : fb;

                exp_big = (e_big == 8'd0) ? 9'd1 : {1'b0, e_big};
                exp_small = (e_small == 8'd0) ? 9'd1 : {1'b0, e_small};
                diff = exp_big - exp_small;

                sig_big = {e_big != 8'd0, f_big, 3'b000};
                sig_small_raw = {e_small != 8'd0, f_small, 3'b000};

                if (diff == 9'd0) begin
                    sig_small = sig_small_raw;
                end else if (diff >= 9'd27) begin
                    sig_small = {26'd0, |sig_small_raw};
                end else begin
                    wide_shift = {sig_small_raw, 27'd0} >> diff;
                    sig_small = {wide_shift[53:28], wide_shift[27] | (|wide_shift[26:0])};
                end

                if (s_big == s_small) begin
                    sum = {1'b0, sig_big} + {1'b0, sig_small};
                    if (sum[27]) begin
                        norm = {sum[27:2], sum[1] | sum[0]};
                        exp_norm = exp_big + 9'd1;
                    end else if (sum[26]) begin
                        norm = sum[26:0];
                        exp_norm = exp_big;
                    end else begin
                        norm = sum[26:0];
                        exp_norm = 9'd0;
                    end
                    mant = norm[25:3];
                    g = norm[2]; r = norm[1]; s = norm[0];
                    inc = g & (r | s | mant[0]);
                    rounded = {1'b0, mant} + {23'd0, inc};
                    if (exp_norm == 9'd0) begin
                        final_exp = (rounded[23] || norm[26]) ? 9'd1 : 9'd0;
                    end else begin
                        final_exp = exp_norm + {8'd0, rounded[23]};
                    end
                    if (final_exp >= 9'd255) f32_add = {s_big, 8'hff, 23'd0};
                    else f32_add = {s_big, final_exp[7:0], rounded[22:0]};
                end else begin
                    diff_sig = sig_big - sig_small;
                    if (diff_sig == 27'd0) begin
                        f32_add = 32'd0;
                    end else begin
                        lzc = clz27(diff_sig);
                        max_shift = exp_big - 9'd1;
                        if ({4'd0, lzc} <= max_shift) begin
                            norm = diff_sig << lzc;
                            exp_norm = exp_big - {4'd0, lzc};
                        end else begin
                            norm = diff_sig << max_shift[4:0];
                            exp_norm = 9'd0;
                        end
                        if (!norm[26]) exp_norm = 9'd0;
                        mant = norm[25:3];
                        g = norm[2]; r = norm[1]; s = norm[0];
                        inc = g & (r | s | mant[0]);
                        rounded = {1'b0, mant} + {23'd0, inc};
                        if (exp_norm == 9'd0) begin
                            final_exp = rounded[23] ? 9'd1 : 9'd0;
                        end else begin
                            final_exp = exp_norm + {8'd0, rounded[23]};
                        end
                        f32_add = {s_big, final_exp[7:0], rounded[22:0]};
                    end
                end
            end
        end
    endfunction

    function automatic [31:0] f32_mul(input [31:0] a, input [31:0] b);
        reg sa, sb, sign;
        reg [7:0] ea, eb;
        reg [22:0] fa, fb;
        reg a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        reg [4:0] lza, lzb;
        reg [23:0] sig_a, sig_b;
        reg signed [10:0] exp_a, exp_b, exp_sum, rshift, exp_out;
        reg [47:0] prod, norm_prod;
        reg [25:0] sub_in;
        reg [51:0] sub_shift;
        reg [24:0] sub_sig;
        reg round_bit, sticky_bit, inc;
        reg [23:0] rounded;
        begin
            sa = a[31]; ea = a[30:23]; fa = a[22:0];
            sb = b[31]; eb = b[30:23]; fb = b[22:0];
            sign = sa ^ sb;
            a_nan = (ea == 8'hff) && (fa != 23'd0);
            b_nan = (eb == 8'hff) && (fb != 23'd0);
            a_inf = (ea == 8'hff) && (fa == 23'd0);
            b_inf = (eb == 8'hff) && (fb == 23'd0);
            a_zero = (ea == 8'd0) && (fa == 23'd0);
            b_zero = (eb == 8'd0) && (fb == 23'd0);

            if (a_nan || b_nan || (a_inf && b_zero) || (b_inf && a_zero)) begin
                f32_mul = 32'h7fc00000;
            end else if (a_inf || b_inf) begin
                f32_mul = {sign, 8'hff, 23'd0};
            end else if (a_zero || b_zero) begin
                f32_mul = {sign, 31'd0};
            end else begin
                if (ea == 8'd0) begin
                    lza = clz24({1'b0, fa});
                    sig_a = {1'b0, fa} << lza;
                    exp_a = 11'sd1 - $signed({6'd0, lza});
                end else begin
                    sig_a = {1'b1, fa};
                    exp_a = $signed({3'd0, ea});
                end
                if (eb == 8'd0) begin
                    lzb = clz24({1'b0, fb});
                    sig_b = {1'b0, fb} << lzb;
                    exp_b = 11'sd1 - $signed({6'd0, lzb});
                end else begin
                    sig_b = {1'b1, fb};
                    exp_b = $signed({3'd0, eb});
                end

                prod = sig_a * sig_b;
                exp_sum = exp_a + exp_b - 11'sd127 + (prod[47] ? 11'sd1 : 11'sd0);
                norm_prod = prod[47] ? prod : (prod << 1);

                if (exp_sum >= 11'sd255) begin
                    f32_mul = {sign, 8'hff, 23'd0};
                end else if (exp_sum <= 11'sd0) begin
                    rshift = 11'sd1 - exp_sum;
                    if (rshift > 11'sd25) begin
                        f32_mul = {sign, 31'd0};
                    end else begin
                        sub_in = {norm_prod[47:23], |norm_prod[22:0]};
                        sub_shift = {sub_in, 26'd0} >> rshift[4:0];
                        sub_sig = {sub_shift[50:27], |sub_shift[26:0]};
                        round_bit = sub_sig[1];
                        sticky_bit = sub_sig[0];
                        inc = round_bit & (sticky_bit | sub_sig[2]);
                        rounded = {1'b0, sub_sig[24:2]} + {23'd0, inc};
                        f32_mul = {sign, rounded[23] ? 8'd1 : 8'd0, rounded[22:0]};
                    end
                end else begin
                    round_bit = norm_prod[23];
                    sticky_bit = |norm_prod[22:0];
                    inc = round_bit & (sticky_bit | norm_prod[24]);
                    rounded = {1'b0, norm_prod[46:24]} + {23'd0, inc};
                    exp_out = exp_sum + (rounded[23] ? 11'sd1 : 11'sd0);
                    if (exp_out >= 11'sd255) f32_mul = {sign, 8'hff, 23'd0};
                    else f32_mul = {sign, exp_out[7:0], rounded[22:0]};
                end
            end
        end
    endfunction

    function automatic [31:0] f32_min_max(input [31:0] a, input [31:0] b, input is_max);
        reg signed [31:0] ka, kb;
        begin
            if (a[30:0] > 31'h7f800000) f32_min_max = a;
            else if (b[30:0] > 31'h7f800000) f32_min_max = b;
            else begin
                ka = $signed(a ^ ({32{a[31]}} & 32'h7fffffff));
                kb = $signed(b ^ ({32{b[31]}} & 32'h7fffffff));
                if (is_max) f32_min_max = (ka > kb) ? a : b;
                else f32_min_max = (ka < kb) ? a : b;
            end
        end
    endfunction

    always @* begin
        case (addr)
            6'h00: rdata = opa;
            6'h04: rdata = opb;
            6'h08: rdata = f32_add(opa, opb);
            6'h0c: rdata = (opb[30:0] > 31'h7f800000) ? 32'h7fc00000 : f32_add(opa, {~opb[31], opb[30:0]});
            6'h10: rdata = f32_mul(opa, opb);
            6'h14: rdata = int_to_f32(opa, 1'b1);
            6'h18: rdata = int_to_f32(opa, 1'b0);
            6'h1c: rdata = f32_to_i32(opa);
            6'h20: rdata = f32_to_u32(opa);
            6'h24: rdata = f32_to_i8(opa);
            6'h28: rdata = f32_to_u8(opa);
            6'h2c: rdata = int_to_f32(opa + opb, 1'b1);
            6'h30: rdata = f32_min_max(opa, opb, 1'b0);
            6'h34: rdata = f32_min_max(opa, opb, 1'b1);
            6'h3c: rdata = 32'h46505531;
            default: rdata = 32'd0;
        endcase
    end
endmodule
`endif
`default_nettype wire
