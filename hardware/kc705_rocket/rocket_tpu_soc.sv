`timescale 1ns/1ps
`default_nettype none
// Rocket: cached memory and uncached MMIO, one system clock.
// Each Wishbone beat is captured before decoding and gets exactly one registered
// response. Arbitration is round robin between beats, including cache refills.
module rocket_tpu_soc #(
    parameter BOOT_HEX = "",
    parameter BOOT_WORDS = 16384,
    parameter PIPELINED_DECODE = 0
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
    localparam IDLE=3'd0, LOCAL=3'd1, EXT_REQ=3'd2, EXT_WAIT=3'd3, RESP=3'd4, DECODE=3'd5;
    reg [2:0] state;
    // Register each master's ACK/ERR separately. Do not decode state, owner,
    // error or the board reset combinationally into the CPU's control path.
    // Local reset register cuts the board-wide reset fanout out of the CPU's
    // synchronous control paths. The bus stays idle while the core is reset.
    reg cpu_reset = 1'b1;
    always @(posedge clk) cpu_reset <= rst || !ready_to_run;
    reg peripheral_reset = 1'b1;
    always @(posedge clk) peripheral_reset <= rst;
    wire i_we;
    wire [31:0] i_wdata;
    wire [3:0] i_sel;
    rocket_wb cpu (
      .clk(clk),.rst(cpu_reset),
      .m_cyc(i_cyc),.m_stb(i_stb),.m_we(i_we),.m_adr(i_adr),.m_dat_w(i_wdata),.m_sel(i_sel),
      .m_dat_r(bus_rdata),.m_ack(termination[0]),.m_err(termination[1]),
      .u_cyc(d_cyc),.u_stb(d_stb),.u_we(d_we),.u_adr(d_adr),.u_dat_w(d_wdata),.u_sel(d_sel),
      .u_dat_r(bus_rdata),.u_ack(termination[2]),.u_err(termination[3])
    );
    // Cached-memory bus address for diagnostics, not retired PC.
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
        addr[31:5] == (32'h20001000 >> 5),
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
    wire rom_address = addr[31:6] == (32'h10000000 >> 6);
    wire timer_address = addr == 32'h20002008;
    reg [31:0] system_cycles = 0;
    always @(posedge clk) begin
        if (rst) system_cycles <= 0;
        else system_cycles <= system_cycles + 1'b1;
    end
    wire local_error = !((rom_address && !write) || boot_address || tpu_address || timer_address ||
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
    synapse32_tpu_peripheral accelerator (
        .clk(clk), .rst_n(!peripheral_reset), .cpu_wr_en(local_access && tpu_address && write),
        .cpu_rd_en(local_access && tpu_address && !write), .cpu_addr(addr[4:0]),
        .cpu_wdata(wdata), .cpu_wstrb(wstrb), .cpu_rdata(tpu_data)
    );
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
                    wdata <= select_data ? d_wdata : i_wdata; wstrb <= select_data ? d_sel : i_sel;
                    write <= select_data ? d_we : i_we;
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
                    else begin
                        state <= RESP; response_data <= 0;
                        response_boot <= boot_address;
                        response_error <= local_error;
                        termination <= terminate_beat(owner_data, local_error);
                        if (boot_address) begin end
                        else if (rom_address) begin
                            case(addr[5:2])
                              0:response_data<=32'h00100293; // li t0,1
                              1:response_data<=32'h01f29293; // slli t0,t0,31
                              2:response_data<=32'h00028067; // jr t0
                              default:response_data<=32'h00000013;
                            endcase
                        end
                        else if (timer_address) response_data <= system_cycles;
                        else if (tpu_address) response_data <= tpu_data;
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
`default_nettype wire
