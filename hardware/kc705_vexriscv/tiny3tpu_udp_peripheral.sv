`timescale 1ns/1ps
`default_nettype none
// CPU packet buffers for the hardware UDP stack. All ports use the system clock;
// the MAC owns PHY clock crossings. A complete RX packet is published atomically
// and held until RELEASE. A TX COMMIT snapshots its metadata and drains BRAM
// independently of the CPU. No DDR, CPU IP stack, or byte-at-a-time TX polling.
module tiny3tpu_udp_peripheral #(
    parameter [31:0] BASE_ADDR = 32'h20004000,
    parameter [15:0] UDP_PORT = 16'd9001
) (
    input wire clk, input wire rst,
    input wire req_valid, output wire req_ready,
    input wire req_write, input wire [31:0] req_addr,
    input wire [31:0] req_wdata, input wire [3:0] req_wstrb,
    output reg resp_valid, input wire resp_ready,
    output wire [31:0] resp_rdata, output reg resp_error,
    input wire rx_valid, output wire rx_ready,
    input wire [31:0] rx_data, input wire rx_last,
    input wire [3:0] rx_last_be, input wire [3:0] rx_error,
    input wire [15:0] rx_src_port, input wire [15:0] rx_dst_port,
    input wire [31:0] rx_ip_address, input wire [15:0] rx_length,
    output reg tx_valid, input wire tx_ready,
    output reg [31:0] tx_data, output wire tx_last,
    output wire [3:0] tx_last_be, output wire [3:0] tx_error,
    output wire [15:0] tx_src_port, output wire [15:0] tx_dst_port,
    output wire [31:0] tx_ip_address, output wire [15:0] tx_length,
    output reg rx_pending, output reg tx_busy,
    output reg [31:0] rx_drop_count, output reg [31:0] rx_bad_count
);
    localparam MAX_BYTES = 1472;
    // 1536-byte apertures; max Ethernet-MTU UDP payload is 1472 bytes.
    reg [31:0] rx_mem [0:383];
    reg [31:0] tx_mem [0:383];
    reg [31:0] cpu_rx_data, response_data;
    reg response_rx;
    assign resp_rdata=response_rx ? cpu_rx_data : response_data;
    reg [15:0] held_rx_length, held_rx_src, held_rx_dst;
    reg [31:0] held_rx_ip;
    reg [15:0] tx_cfg_length, tx_cfg_src, tx_cfg_dst;
    reg [31:0] tx_cfg_ip;
    reg [8:0] tx_index;
    reg rx_active, rx_discard, rx_invalid;
    reg [16:0] rx_bytes;
    reg [15:0] incoming_length, incoming_src, incoming_dst;
    reg [31:0] incoming_ip;
    reg dropped_sticky, bad_sticky;

    wire [12:0] offset = req_addr[12:0];
    wire in_window = req_addr[31:13] == BASE_ADDR[31:13];
    wire aligned = req_addr[1:0] == 0;
    wire rx_aperture = offset >= 13'h400 && offset < 13'ha00;
    wire tx_aperture = offset >= 13'h1000 && offset < 13'h1600;
    assign req_ready = !resp_valid;
    wire access = req_valid && req_ready;
    wire command = access && req_write && in_window && aligned &&
                   offset == 13'h01c && req_wstrb[0];
    wire bad_command = (req_wdata[7:3] != 0) ||
                       (req_wdata[1] && (tx_busy || tx_cfg_length == 0 ||
                                        tx_cfg_length > MAX_BYTES || tx_cfg_src != UDP_PORT));
    wire release_rx = command && !bad_command && req_wdata[0];
    wire launch_tx = command && !bad_command && req_wdata[1];
    wire clear_counts = command && !bad_command && req_wdata[2];

    // Always consume or discard a whole incoming packet. Backpressure cannot
    // stop a physical Ethernet sender; never overwrite the CPU's held packet.
    assign rx_ready = !rst;
    function [2:0] last_bytes;
        input [3:0] last_be;
        begin
            case(last_be)
                4'b0001: last_bytes=1;
                4'b0010: last_bytes=2;
                4'b0100: last_bytes=3;
                4'b1000: last_bytes=4;
                default: last_bytes=0;
            endcase
        end
    endfunction
    wire [16:0] before_bytes = rx_active ? rx_bytes : 17'd0;
    wire [16:0] next_bytes = before_bytes + (rx_last ? {14'd0,last_bytes(rx_last_be)} : 17'd4);
    wire discard_beat = rx_active ? rx_discard : (rx_pending && !release_rx);
    wire bad_beat = (rx_active && rx_invalid) || (|rx_error) ||
        (rx_length == 0 || rx_length > MAX_BYTES || rx_dst_port != UDP_PORT) ||
        (rx_active && (rx_length != incoming_length || rx_ip_address != incoming_ip ||
                       rx_src_port != incoming_src || rx_dst_port != incoming_dst)) ||
        next_bytes > MAX_BYTES || next_bytes < before_bytes ||
        (rx_last && (last_bytes(rx_last_be)==0 || next_bytes != {1'b0,rx_length}));
    always @(posedge clk) begin
        if (!rst && rx_valid && rx_ready && !discard_beat && !bad_beat)
            rx_mem[before_bytes[10:2]] <= rx_data;
    end
    always @(posedge clk) begin
        if (rst) begin
            rx_pending<=0;rx_active<=0;rx_discard<=0;rx_invalid<=0;rx_bytes<=0;
            incoming_length<=0;incoming_src<=0;incoming_dst<=0;incoming_ip<=0;
            held_rx_length<=0;held_rx_src<=0;held_rx_dst<=0;held_rx_ip<=0;
            rx_drop_count<=0;rx_bad_count<=0;dropped_sticky<=0;bad_sticky<=0;
        end else begin
            if (release_rx) rx_pending<=0;
            if (clear_counts) begin
                rx_drop_count<=0;rx_bad_count<=0;dropped_sticky<=0;bad_sticky<=0;
            end
            if (rx_valid && rx_ready) begin
                if (!rx_active) begin
                    incoming_length<=rx_length;incoming_src<=rx_src_port;
                    incoming_dst<=rx_dst_port;incoming_ip<=rx_ip_address;
                end
                rx_active<=!rx_last;rx_discard<=discard_beat;rx_invalid<=bad_beat;
                rx_bytes<=next_bytes;
                if (rx_last) begin
                    if (discard_beat) begin
                        rx_drop_count<=clear_counts ? 1 : rx_drop_count+1'b1;
                        dropped_sticky<=1;
                    end else if (bad_beat) begin
                        rx_bad_count<=clear_counts ? 1 : rx_bad_count+1'b1;bad_sticky<=1;
                    end else begin
                        rx_pending<=1;held_rx_length<=rx_length;held_rx_src<=rx_src_port;
                        held_rx_dst<=rx_dst_port;held_rx_ip<=rx_ip_address;
                    end
                end
            end
        end
    end

    assign tx_src_port=tx_cfg_src;
    assign tx_dst_port=tx_cfg_dst;
    assign tx_ip_address=tx_cfg_ip;
    assign tx_length=tx_cfg_length;
    assign tx_last=({7'd0,tx_index,2'b00}+18'd4 >= {2'b0,tx_cfg_length});
    assign tx_last_be=tx_last ? (4'b0001 << ((tx_cfg_length-1'b1)&3)) : 4'b0000;
    assign tx_error=0;
    // Synchronous BRAM read with a holding register. One beat every two system
    // clocks sustains 200 MB/s at 100 MHz, exceeding the 1 Gb/s PHY requirement.
    always @(posedge clk) begin
        if (rst) begin tx_busy<=0;tx_valid<=0;tx_data<=0;tx_index<=0; end
        else begin
            if (launch_tx) begin tx_busy<=1;tx_index<=0; end
            if (tx_busy && !tx_valid) begin
                tx_data<=tx_mem[tx_index];tx_valid<=1;
            end
            if (tx_valid && tx_ready) begin
                tx_valid<=0;
                if (tx_last) tx_busy<=0;
                else tx_index<=tx_index+1'b1;
            end
        end
    end

    // Keep the BRAM output register free of reset and peripheral response muxes.
    always @(posedge clk) begin
        if(access && !req_write && in_window && aligned && rx_aperture)
            cpu_rx_data<=rx_mem[(offset-13'h400)>>2];
    end

    integer lane;
    always @(posedge clk) begin
        if (!rst && access && req_write && in_window && aligned && tx_aperture && !tx_busy)
            for (lane=0;lane<4;lane=lane+1)
                if (req_wstrb[lane]) tx_mem[(offset-13'h1000)>>2][8*lane+:8]<=req_wdata[8*lane+:8];
    end
    function [31:0] merge_bytes;
        input [31:0] old_data,new_data;
        input [3:0] strobe;
        integer i;
        begin
            merge_bytes=old_data;
            for(i=0;i<4;i=i+1) if(strobe[i]) merge_bytes[8*i+:8]=new_data[8*i+:8];
        end
    endfunction
    wire [31:0] merged_tx_length=merge_bytes({16'd0,tx_cfg_length},req_wdata,req_wstrb);
    wire [31:0] merged_tx_ports=merge_bytes({tx_cfg_dst,tx_cfg_src},req_wdata,req_wstrb);
    always @(posedge clk) begin
        if (rst) begin
            resp_valid<=0;response_data<=0;response_rx<=0;resp_error<=0;
            tx_cfg_length<=0;tx_cfg_ip<=0;tx_cfg_src<=UDP_PORT;tx_cfg_dst<=0;
        end else begin
            if(resp_valid && resp_ready) resp_valid<=0;
            if(access) begin
                resp_valid<=1;response_data<=0;response_rx<=0;resp_error<=0;
                if(!in_window || !aligned) resp_error<=1;
                else if(req_write) begin
                    if(tx_aperture) resp_error<=tx_busy;
                    else case(offset)
                        13'h010: if(tx_busy || merged_tx_length[31:16]!=0) resp_error<=1;
                                 else tx_cfg_length<=merged_tx_length[15:0];
                        13'h014: if(tx_busy) resp_error<=1;
                                 else tx_cfg_ip<=merge_bytes(tx_cfg_ip,req_wdata,req_wstrb);
                        13'h018: if(tx_busy) resp_error<=1;
                                 else begin tx_cfg_src<=merged_tx_ports[15:0];tx_cfg_dst<=merged_tx_ports[31:16];end
                        13'h01c: resp_error<=req_wstrb[0] && bad_command;
                        default: resp_error<=1;
                    endcase
                end else if(rx_aperture) begin
                    response_rx<=1;resp_error<=!rx_pending;
                end else case(offset)
                    13'h000: response_data<={28'd0,bad_sticky,dropped_sticky,!tx_busy,rx_pending};
                    13'h004: response_data<={16'd0,held_rx_length};
                    13'h008: response_data<=held_rx_ip;
                    13'h00c: response_data<={held_rx_dst,held_rx_src};
                    13'h010: response_data<={16'd0,tx_cfg_length};
                    13'h014: response_data<=tx_cfg_ip;
                    13'h018: response_data<={tx_cfg_dst,tx_cfg_src};
                    13'h020: response_data<=rx_drop_count;
                    13'h024: response_data<=rx_bad_count;
                    13'h028: response_data<=32'h00010000;
                    default: resp_error<=1;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
