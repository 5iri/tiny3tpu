`default_nettype none
// Compact diagnostic frames on the KC705 CP2103 USB UART (115200 8N1).
// A frame is A5 5A, sequence, sticky flags, four debug bytes (LSB first),
// and status {3'b0, raw_dq0, locked, failed, passed, done}. raw_dq0 is the
// existing IDELAY output immediately before the receive serializer.
module kc705_uberddr3_uart_diag #(
    parameter integer CLK_HZ = 83333333
) (
    input wire clk, rst_n,
    input wire [31:0] debug,
    input wire done, passed, failed, locked, raw_dq0,
    output reg tx = 1'b1
);
    localparam integer BAUD_DIV = (CLK_HZ + 57600) / 115200;
    localparam integer FRAME_DIV = CLK_HZ / 1000;
    reg [16:0] interval = 0;
    reg [15:0] baud_count = 0;
    reg [7:0] sticky = 0;
    reg [7:0] frame_seq = 0;
    reg [71:0] frame = 0;
    reg [7:0] data_shift = 0;
    reg [3:0] byte_index = 0;
    reg [3:0] bit_index = 0;
    reg [1:0] state = 0;

    // These flags stay set until external reset, preserving short events.
    // 0=PHY ready, 1=ODT requested, 2=DQS toggle requested,
    // 3=DQS pad output enabled, 4=DQ pad input enabled,
    // 5=prime DQ sampled low, 6=prime DQ sampled high, 7=pre-serializer DQ0 high.
    always @(posedge clk) begin
        if (!rst_n) begin
            tx <= 1'b1;
            interval <= 0;
            baud_count <= 0;
            sticky <= 0;
            frame_seq <= 0;
            frame <= 0;
            data_shift <= 0;
            byte_index <= 0;
            bit_index <= 0;
            state <= 0;
        end else begin
            sticky[0] <= sticky[0] | debug[29];
            sticky[1] <= sticky[1] | debug[28];
            sticky[2] <= sticky[2] | debug[27];
            sticky[3] <= sticky[3] | (debug[28] && !debug[26]);
            sticky[4] <= sticky[4] | (debug[28] && debug[25]);
            sticky[5] <= sticky[5] | (debug[28] && !debug[24]);
            sticky[6] <= sticky[6] | (debug[28] && debug[24]);
            sticky[7] <= sticky[7] | (debug[28] && raw_dq0);
            if (interval < FRAME_DIV-1) interval <= interval + 1'b1;
            if (state != 0) begin
                if (baud_count == BAUD_DIV-1) begin
                    baud_count <= 0;
                    case (state)
                        2'd1: begin
                            tx <= data_shift[0];
                            data_shift <= {1'b0, data_shift[7:1]};
                            bit_index <= 1;
                            state <= 2;
                        end
                        2'd2: begin
                            if (bit_index == 8) begin
                                tx <= 1'b1;
                                state <= 3;
                            end else begin
                                tx <= data_shift[0];
                                data_shift <= {1'b0, data_shift[7:1]};
                                bit_index <= bit_index + 1'b1;
                            end
                        end
                        2'd3: begin
                            if (byte_index == 8) begin
                                state <= 0;
                                tx <= 1'b1;
                            end else begin
                                byte_index <= byte_index + 1'b1;
                                data_shift <= frame[7:0];
                                frame <= {8'b0, frame[71:8]};
                                tx <= 1'b0;
                                state <= 1;
                            end
                        end
                        default: state <= 0;
                    endcase
                end else baud_count <= baud_count + 1'b1;
            end else if (interval == FRAME_DIV-1) begin
                interval <= 0;
                frame_seq <= frame_seq + 1'b1;
                // First byte starts immediately; the remaining eight bytes
                // are shifted out from frame on subsequent stop bits.
                frame <= {3'b0, raw_dq0, locked, failed, passed, done,
                          debug[31:24], debug[23:16], debug[15:8], debug[7:0],
                          sticky, frame_seq, 8'h5a};
                data_shift <= 8'ha5;
                byte_index <= 0;
                bit_index <= 0;
                baud_count <= 0;
                tx <= 1'b0;
                state <= 1;
            end
        end
    end
endmodule
`default_nettype wire
