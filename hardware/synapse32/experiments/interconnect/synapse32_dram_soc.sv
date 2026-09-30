`timescale 1ns/1ps
`default_nettype none
// Bare-metal, uncached CPU/TPU system with synchronous on-chip boot RAM and a
// variable-latency external memory/controller-CSR port. This is not a DDR PHY.
// All bus/peripheral logic uses clk; only the unchanged CPU is clock-enabled.
module synapse32_dram_soc #(
    parameter BOOT_HEX = "",
    parameter BOOT_WORDS = 16384
) (
    input wire clk, input wire rst, input wire ready_to_run,
    input wire uart_rx, output wire uart_tx,
    output wire fault, output wire [31:0] pc_debug,
    output wire ext_req_valid, input wire ext_req_ready,
    output wire ext_req_write, output wire [31:0] ext_req_addr,
    output wire [31:0] ext_req_wdata, output wire [3:0] ext_req_wstrb,
    input wire ext_resp_valid, output wire ext_resp_ready,
    input wire [31:0] ext_resp_rdata, input wire ext_resp_error,
    output reg report_valid, output reg [31:0] report_data,
    output reg exit_valid, output reg [31:0] exit_code
);
    wire cpu_clk, cpu_step;
    wire [31:0] instr, cpu_rdata, rd_addr, wr_addr, wr_data;
    wire rd_en, wr_en;
    wire [3:0] wr_strb;
    wire [2:0] load_type;
    synapse32_clock_enable clock_enable (
        .clk(clk), .enable(rst || cpu_step), .cpu_clk(cpu_clk)
    );
    riscv_cpu cpu (
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
    // 1 GiB DRAM at 0x40000000; controller CSRs at 0xf0000000..0xf000ffff.
    wire external_address = req_addr[31:30]==2'b01 || req_addr[31:16]==16'hf000;
    wire boot_address;
    generate
        // An aligned power-of-two boot window needs only upper-bit equality.
        // Limit specialization to the non-wrapping 0x80000000..0xffffffff range.
        if (BOOT_WORDS > 0 && BOOT_WORDS <= 536870912 &&
            (BOOT_WORDS & (BOOT_WORDS-1)) == 0) begin : boot_power_of_two
            localparam BOOT_ADDR_BITS = $clog2(BOOT_WORDS) + 2;
            assign boot_address = (req_addr >> BOOT_ADDR_BITS) ==
                                  (32'h80000000 >> BOOT_ADDR_BITS);
        end else begin : boot_general
            assign boot_address = req_addr>=32'h80000000 &&
                (req_addr-32'h80000000)<BOOT_WORDS*4;
        end
    endgenerate
    wire uart_address = req_addr[31:5]==(32'h20000000>>5);
    wire tpu_address = req_addr[31:5]==(32'h20001000>>5);
    reg local_valid, local_error, external_pending, local_boot;
    reg [31:0] local_rdata;
    reg [31:0] boot_rdata;
    wire idle = !local_valid && !external_pending;
    assign req_ready = !rst && idle && (!external_address || ext_req_ready);
    wire accept = req_valid && req_ready;
    assign ext_req_valid = !rst && idle && req_valid && external_address;
    assign ext_req_write=req_write;
    assign ext_req_addr=req_addr;
    assign ext_req_wdata=req_wdata;
    assign ext_req_wstrb=req_wstrb;
    assign ext_resp_ready=!rst && external_pending && resp_ready;
    assign resp_valid=local_valid || (external_pending && ext_resp_valid);
    assign resp_rdata=external_pending ? ext_resp_rdata : local_boot ? boot_rdata : local_rdata;
    assign resp_error=external_pending ? ext_resp_error : local_error;

    // Synchronous read, byte-write boot SRAM maps to block RAM. Reset does not
    // clear the entire array. Firmware startup initializes its own BSS.
    reg [31:0] boot_mem [0:BOOT_WORDS-1];
    initial if (BOOT_HEX != "") $readmemh(BOOT_HEX, boot_mem);
    wire [$clog2(BOOT_WORDS)-1:0] boot_index=(req_addr-32'h80000000)>>2;
    wire [31:0] tpu_data, uart_data;
    synapse32_tpu_peripheral accelerator (
        .clk(clk), .rst_n(!rst), .cpu_wr_en(accept && tpu_address && req_write),
        .cpu_rd_en(accept && tpu_address && !req_write), .cpu_addr(req_addr[4:0]),
        .cpu_wdata(req_wdata), .cpu_wstrb(req_wstrb), .cpu_rdata(tpu_data)
    );
    uart serial (
        .clk(clk), .rst(rst), .addr(req_addr), .write_data(req_wdata),
        .write_enable(accept && uart_address && req_write && req_wstrb==15),
        .read_enable(accept && uart_address && !req_write),
        .read_data(uart_data), .uart_valid(), .interrupt(), .tx(uart_tx), .rx(uart_rx)
    );
    integer lane;
    always @(posedge clk) begin
        if (accept && boot_address) begin
            if (!req_write) boot_rdata <= boot_mem[boot_index];
            for (lane=0; lane<4; lane=lane+1)
                if (req_write && req_wstrb[lane])
                    boot_mem[boot_index][lane*8 +: 8] <= req_wdata[lane*8 +: 8];
        end
        if (rst) begin
            local_valid<=0; local_error<=0; local_rdata<=0; external_pending<=0; local_boot<=0;
            report_valid<=0; report_data<=0; exit_valid<=0; exit_code<=0;
        end else begin
            report_valid<=0; exit_valid<=0;
            if (resp_valid && resp_ready) begin local_valid<=0; external_pending<=0; end
            if (accept) begin
                if (external_address) external_pending<=1;
                else begin
                    local_valid<=1; local_error<=0; local_rdata<=0; local_boot<=boot_address;
                    if (boot_address) begin end
                    else if (tpu_address) local_rdata<=tpu_data;
                    else if (uart_address) begin
                        local_rdata<=uart_data;
                        if (req_write && req_wstrb!=15) local_error<=1;
                    end else if (req_addr==32'h20002004 && req_write && req_wstrb==15) begin
                        report_valid<=1; report_data<=req_wdata;
                    end else if (req_addr==32'h20002000 && req_write && req_wstrb==15) begin
                        exit_valid<=1; exit_code<=req_wdata;
                    end else local_error<=1;
                end
            end
        end
    end
endmodule
`default_nettype wire
