`timescale 1ns/1ps
`default_nettype none
// Clause 22 management for the KC705's reset-strapped 88E1111 at address 7.
// Advertise 1000BASE-T full duplex only, restart auto-negotiation, then poll BMSR.
// MDC is 2 MHz from 100 MHz sys; reset is held for 10 ms and followed by 10 ms idle.
module kc705_phy_mdio #(
    parameter integer RESET_CYCLES = 1000000,
    parameter integer POLL_CYCLES = 1000000,
    parameter [4:0] PHY_ADDR = 5'd7
) (
    input wire clk, input wire rst,
    output reg phy_rst_n, output reg mdc, inout wire mdio,
    output reg configured, output reg link_up, output reg mdio_fault,
    output reg [15:0] basic_status
);
    reg [31:0] delay_count;
    reg [5:0] divider;
    reg [6:0] bit_index;
    reg [63:0] frame;
    reg [15:0] read_data;
    reg read_command, turnaround_ok;
    reg [2:0] command;
    reg [2:0] state;
    localparam RESET=0, SETTLE=1, PREPARE=2, SHIFT=3, COMPLETE=4, WAIT_POLL=5;
    wire drive = state==SHIFT && (!read_command || bit_index<46);
    assign mdio = drive ? frame[63-bit_index] : 1'bz;
    function [63:0] write_frame;
        input [4:0] address;
        input [15:0] value;
        begin write_frame={32'hffffffff,2'b01,2'b01,PHY_ADDR,address,2'b10,value}; end
    endfunction
    function [63:0] read_frame;
        input [4:0] address;
        begin read_frame={32'hffffffff,2'b01,2'b10,PHY_ADDR,address,2'b00,16'b0}; end
    endfunction
    always @(posedge clk) begin
        if(rst) begin
            phy_rst_n<=0;mdc<=0;configured<=0;link_up<=0;mdio_fault<=0;basic_status<=0;
            delay_count<=0;divider<=0;bit_index<=0;frame<=0;read_data<=0;
            read_command<=0;turnaround_ok<=0;command<=0;state<=RESET;
        end else case(state)
            RESET: if(delay_count==RESET_CYCLES-1) begin
                phy_rst_n<=1;delay_count<=0;state<=SETTLE;
            end else delay_count<=delay_count+1;
            SETTLE: if(delay_count==RESET_CYCLES-1) begin
                delay_count<=0;state<=PREPARE;
            end else delay_count<=delay_count+1;
            PREPARE: begin
                // Register 4: IEEE selector only (disable 10/100 advertisements).
                // Register 9: 1000BASE-T full-duplex advertisement.
                // BMCR: enable/restart auto-negotiation. No vendor register writes.
                case(command)
                    0: frame<=write_frame(5'd4,16'h0001);
                    1: frame<=write_frame(5'd9,16'h0200);
                    2: frame<=write_frame(5'd0,16'h1200);
                    default: frame<=read_frame(5'd1);
                endcase
                read_command<=command>=3;read_data<=0;turnaround_ok<=0;
                bit_index<=0;divider<=0;mdc<=0;state<=SHIFT;
            end
            SHIFT: if(divider==24) begin
                divider<=0;
                if(!mdc) begin
                    mdc<=1;
                    if(read_command && bit_index==47) turnaround_ok<=!mdio;
                    if(read_command && bit_index>=48) read_data<={read_data[14:0],mdio};
                end else begin
                    mdc<=0;
                    if(bit_index==63) state<=COMPLETE;
                    else bit_index<=bit_index+1;
                end
            end else divider<=divider+1;
            COMPLETE: begin
                if(command<3) begin command<=command+1;state<=PREPARE;end
                else if(command==3) begin
                    // BMSR link is latch-low: discard the first read.
                    command<=4;state<=PREPARE;
                    if(!turnaround_ok) begin mdio_fault<=1;configured<=0;link_up<=0;end
                end else begin
                    configured<=turnaround_ok;mdio_fault<=!turnaround_ok;
                    basic_status<=read_data;link_up<=turnaround_ok && read_data[2] && read_data[5];
                    delay_count<=0;state<=WAIT_POLL;
                end
            end
            WAIT_POLL: if(delay_count==POLL_CYCLES-1) begin command<=3;state<=PREPARE;end
                       else delay_count<=delay_count+1;
            default: state<=RESET;
        endcase
    end
endmodule
`default_nettype wire
