`timescale 1ns/1ps
// KC705: PCA9548 channel 5 -> ADV7511, 640x480/60, BT.601 16-bit 4:2:2.
// Register provenance and limitations: ../ADV7511_REGISTERS.md.
module kc705_hdmi_init #(
    parameter integer CLOCK_HZ = 25200000,
    parameter integer I2C_HZ = 100000,
    parameter integer RETRY_LIMIT = 3, // total attempts per I2C transaction
    parameter integer STARTUP_MS = 200,
    parameter integer POLL_MS = 100,
    parameter integer STRETCH_TIMEOUT_MS = 10,
    parameter integer LOCK_POLL_LIMIT = 20
) (
    input wire clk,
    input wire reset,
    inout wire scl,
    inout wire sda,
    output wire mux_reset_n,
    output reg configured,
    output reg error
);
    localparam integer STARTUP_CYCLES = (CLOCK_HZ / 1000) * STARTUP_MS;
    localparam integer POLL_CYCLES = (CLOCK_HZ / 1000) * POLL_MS;
    localparam [3:0] BOOT=0, MUX=1, STATUS=2, IRQ=3, CLEAR_IRQ=4,
        PROGRAM=5, VERIFY_STATUS=6, VERIFY_IRQ=7, PLL=8, PAUSE=9, FAILED=10;
    reg [3:0] state;
    reg [31:0] delay_count;
    reg [7:0] index;
    integer attempts, lock_polls;
    reg pending, start;
    reg [23:0] tx;
    reg [1:0] tx_count;
    reg read_one;
    wire done, failed;
    wire [7:0] rx;
    assign mux_reset_n = !reset;

    // All registers are reloaded after an HPD event: the ADV7511 loses part
    // of its register state on HPD low, even when the FPGA is not reset.
    localparam integer REGISTER_COUNT = 67;
    localparam [7:0] LAST_REGISTER = 8'(REGISTER_COUNT-1);
    function automatic [15:0] setting(input [7:0] n);
        begin
            case (n)
                0: setting=16'h4110; // power up; preserve fixed bit 4
                1: setting=16'h9803;
                2: setting=16'h9ae0;
                3: setting=16'h9c30;
                4: setting=16'h9d61;
                5: setting=16'ha2a4;
                6: setting=16'ha3a4;
                7: setting=16'he0d0;
                8: setting=16'hf900;
                9: setting=16'h1501; // SDR 16/20/24-bit 4:2:2, separate sync
               10: setting=16'h1634; // 8 bits/component, style 2, RGB output
               11: setting=16'h1700; // pass sync polarity, external DE, 4:3
               12: setting=16'h4808; // right justified; KC705 board bus = {C,Y}
               13: setting=16'hba60; // input clock delay 0 ns
               14: setting=16'hd600; // use physical HPD, no input clock gating
               15: setting=16'h4000; // optional packets off
               16: setting=16'h4401; // audio/NCTS/AVI off while programming
               17: setting=16'h0b0e; // SPDIF disabled, reserved/default bits
               18: setting=16'h0c00; // I2S inputs disabled
               19: setting=16'haf06; // HDMI; HDCP and frame encryption off
               20: setting=16'h3bc0; // manual x1 repeat; reserved bit 7 stays 1
               21: setting=16'h3c01; // VIC 1: 640x480, 4:3
               // Table 59: BT.601 studio-range YCbCr -> full-range RGB.
               // CSC update mode is held until every coefficient is written.
               22: setting=16'h1a24;
               23: setting=16'h18e6;
               24: setting=16'h1969;
               25: setting=16'h1bac;
               26: setting=16'h1c00;
               27: setting=16'h1d00;
               28: setting=16'h1e1c;
               29: setting=16'h1f81;
               30: setting=16'h201c;
               31: setting=16'h21bc;
               32: setting=16'h2204;
               33: setting=16'h23ad;
               34: setting=16'h241e;
               35: setting=16'h256e;
               36: setting=16'h2602;
               37: setting=16'h2720;
               38: setting=16'h281f;
               39: setting=16'h29fe;
               40: setting=16'h2a04;
               41: setting=16'h2bad;
               42: setting=16'h2c08;
               43: setting=16'h2d1a;
               44: setting=16'h2e1b;
               45: setting=16'h2fa9;
               46: setting=16'h1a04; // commit CSC coefficients
               47: setting=16'h4ac0; // AVI update mode + automatic checksum
               48: setting=16'h5202;
               49: setting=16'h530d;
               50: setting=16'h5502; // RGB, underscan, no bars/active-format
               51: setting=16'h5610; // 4:3, RGB has no YCbCr colorimetry code
               52: setting=16'h5708; // full-range RGB
               53: setting=16'h5900;
               54: setting=16'h5a00;
               55: setting=16'h5b00;
               56: setting=16'h5c00;
               57: setting=16'h5d00;
               58: setting=16'h5e00;
               59: setting=16'h5f00;
               60: setting=16'h6000;
               61: setting=16'h6100;
               62: setting=16'h4a80; // commit AVI packet
               63: setting=16'ha100; // enable TMDS channels and clock driver
               64: setting=16'h4b80; // clear a previous sink AVMUTE request
               65: setting=16'h4080; // send GCP carrying clear-AVMUTE
               66: setting=16'h4411; // AVI on; all audio packets remain off
              default: setting=16'h4411;
            endcase
        end
    endfunction

    kc705_hdmi_i2c_master #(.CLOCK_HZ(CLOCK_HZ), .I2C_HZ(I2C_HZ),
        .STRETCH_TIMEOUT_MS(STRETCH_TIMEOUT_MS)) bus (
        .clk(clk), .reset(reset), .scl(scl), .sda(sda), .start(start),
        .tx(tx), .tx_count(tx_count), .read_one(read_one),
        .done(done), .failed(failed), .rx(rx)
    );

    always @(posedge clk) begin
        if (reset) begin
            state<=BOOT; delay_count<=0; index<=0; attempts<=0;
            lock_polls<=0; pending<=0; start<=0; tx<=0;
            tx_count<=0; read_one<=0; configured<=0; error<=0;
        end else begin
            start<=0;
            if (state==BOOT) begin
                if (delay_count>=STARTUP_CYCLES) begin
                    state<=MUX; delay_count<=0;
                end else delay_count<=delay_count+1;
            end else if (state==PAUSE) begin
                if (delay_count>=POLL_CYCLES) begin
                    state<=STATUS; delay_count<=0;
                end else delay_count<=delay_count+1;
            end else if (state!=FAILED) begin
                if (!pending) begin
                    pending<=1; start<=1; tx_count<=3; read_one<=0;
                    case (state)
                        MUX: begin tx<=24'he82000; tx_count<=2; end
                        STATUS, VERIFY_STATUS: begin
                            tx<=24'h724200; tx_count<=2; read_one<=1;
                        end
                        IRQ, VERIFY_IRQ: begin
                            tx<=24'h729600; tx_count<=2; read_one<=1;
                        end
                        PLL: begin
                            tx<=24'h729e00; tx_count<=2; read_one<=1;
                        end
                        CLEAR_IRQ: tx<=24'h729680;
                        PROGRAM: tx<={8'h72, setting(index)};
                        default: tx<=0;
                    endcase
                end else if (done) begin
                    pending<=0;
                    if (failed) begin
                        configured<=0;
                        if (attempts+1>=RETRY_LIMIT) begin
                            error<=1; state<=FAILED;
                        end else attempts<=attempts+1;
                    end else begin
                        attempts<=0;
                        case (state)
                            MUX: state<=STATUS;
                            STATUS: begin
                                if (!rx[6]) begin
                                    configured<=0; lock_polls<=0; state<=PAUSE;
                                end else if (configured) state<=IRQ;
                                else state<=CLEAR_IRQ;
                            end
                            IRQ: begin
                                if (rx[7]) begin configured<=0; state<=CLEAR_IRQ; end
                                else state<=PLL;
                            end
                            CLEAR_IRQ: begin index<=0; state<=PROGRAM; end
                            PROGRAM: begin
                                if (index==LAST_REGISTER) state<=VERIFY_STATUS;
                                else index<=index+1;
                            end
                            VERIFY_STATUS: begin
                                if (!rx[6]) begin
                                    configured<=0; lock_polls<=0; state<=PAUSE;
                                end else state<=VERIFY_IRQ;
                            end
                            VERIFY_IRQ: begin
                                if (rx[7]) begin configured<=0; state<=CLEAR_IRQ; end
                                else state<=PLL;
                            end
                            PLL: begin
                                state<=PAUSE;
                                if (rx[4]) begin configured<=1; lock_polls<=0; end
                                else begin
                                    configured<=0; lock_polls<=lock_polls+1;
                                    if (lock_polls+1>=LOCK_POLL_LIMIT) begin
                                        error<=1; state<=FAILED;
                                    end
                                end
                            end
                            default: state<=FAILED;
                        endcase
                    end
                end
            end
        end
    end
endmodule

// Single-master, open-drain I2C engine. Writes 2/3 bytes; optional combined
// register read uses repeated START and a master NACK on the final byte.
// A stuck SDA triggers nine recovery clocks and STOP. SCL stretching is bounded.
module kc705_hdmi_i2c_master #(
    parameter integer CLOCK_HZ=25200000,
    parameter integer I2C_HZ=100000,
    parameter integer STRETCH_TIMEOUT_MS=10
) (
    input wire clk, reset, start,
    input wire [23:0] tx,
    input wire [1:0] tx_count,
    input wire read_one,
    inout wire scl, sda,
    output reg done, failed,
    output reg [7:0] rx
);
    localparam integer Q = (CLOCK_HZ + 4*I2C_HZ - 1)/(4*I2C_HZ);
    localparam integer TIMEOUT = (CLOCK_HZ/1000)*STRETCH_TIMEOUT_MS;
    localparam [5:0] IDLE=0, START_WAIT=1, START_SDA=2, START_HOLD=3,
        START_FALL=4, BIT_SETUP=5, BIT_RISE=6, BIT_HIGH=7, BIT_FALL=8,
        ACK_SETUP=9, ACK_RISE=10, ACK_HIGH=11, ACK_FALL=12,
        RESTART_SETUP=13, RESTART_RISE=14, RESTART_HIGH=15,
        READ_SETUP=16, READ_RISE=17, READ_HIGH=18, READ_FALL=19,
        NAK_SETUP=20, NAK_RISE=21, NAK_HIGH=22, NAK_FALL=23,
        STOP_SETUP=24, STOP_RISE=25, STOP_HIGH=26, STOP_RELEASE=27,
        STOP_DONE=28, CLEAR_LOW=29, CLEAR_RISE=30, CLEAR_HIGH=31, CLEAR_FALL=32;
    reg [5:0] state;
    reg scl_low, sda_low;
    (* ASYNC_REG = "TRUE" *) reg [1:0] scl_sync, sda_sync;
    wire scl_in=scl_sync[1], sda_in=sda_sync[1];
    assign scl=scl_low ? 1'b0 : 1'bz;
    assign sda=sda_low ? 1'b0 : 1'bz;
    reg [31:0] divider, stretch;
    reg [15:0] bytes;
    reg [7:0] byte_value, address_read;
    reg [1:0] remaining;
    reg [2:0] bit_index;
    reg want_read, read_address, ack_bad, recovered, recovery_stop;
    reg [3:0] recovery_clocks;
    always @(posedge clk) begin
        if (reset) begin scl_sync<=3; sda_sync<=3; end
        else begin scl_sync<={scl_sync[0],scl}; sda_sync<={sda_sync[0],sda}; end
    end
    always @(posedge clk) begin
        if (reset) begin
            state<=IDLE; scl_low<=0; sda_low<=0; divider<=0; stretch<=0;
            done<=0; failed<=0; rx<=0; bytes<=0; byte_value<=0;
            address_read<=0; remaining<=0; bit_index<=0; want_read<=0;
            read_address<=0; ack_bad<=0; recovered<=0; recovery_stop<=0;
            recovery_clocks<=0;
        end else begin
            done<=0;
            if (state==IDLE) begin
                divider<=0; stretch<=0;
                if (start) begin
                    bytes<=tx[15:0]; byte_value<=tx[23:16];
                    address_read<={tx[23:17],1'b1}; remaining<=tx_count;
                    want_read<=read_one; read_address<=0; bit_index<=7;
                    failed<=0; rx<=0; recovered<=0; recovery_stop<=0;
                    scl_low<=0; sda_low<=0; state<=START_WAIT;
                end
            end else if (!scl_low && !scl_in) begin
                divider<=0;
                if (stretch>=TIMEOUT) begin
                    failed<=1; done<=1; scl_low<=0; sda_low<=0; state<=IDLE;
                end else stretch<=stretch+1;
            end else begin
                stretch<=0;
                if (divider<Q-1) divider<=divider+1;
                else begin
                    divider<=0;
                    case (state)
                        START_WAIT: begin
                            if (sda_in) state<=START_SDA;
                            else if (!recovered) begin
                                recovered<=1; recovery_clocks<=0; state<=CLEAR_LOW;
                            end else begin failed<=1; done<=1; state<=IDLE; end
                        end
                        START_SDA: begin sda_low<=1; state<=START_HOLD; end
                        START_HOLD: state<=START_FALL;
                        START_FALL: begin scl_low<=1; state<=BIT_SETUP; end
                        BIT_SETUP: begin sda_low<=!byte_value[bit_index]; state<=BIT_RISE; end
                        BIT_RISE: begin scl_low<=0; state<=BIT_HIGH; end
                        BIT_HIGH: state<=BIT_FALL;
                        BIT_FALL: begin
                            scl_low<=1;
                            if (bit_index==0) state<=ACK_SETUP;
                            else begin bit_index<=bit_index-1; state<=BIT_SETUP; end
                        end
                        ACK_SETUP: begin sda_low<=0; state<=ACK_RISE; end
                        ACK_RISE: begin scl_low<=0; state<=ACK_HIGH; end
                        ACK_HIGH: begin ack_bad<=sda_in; state<=ACK_FALL; end
                        ACK_FALL: begin
                            scl_low<=1;
                            if (ack_bad) begin failed<=1; state<=STOP_SETUP; end
                            else if (read_address) begin bit_index<=7; state<=READ_SETUP; end
                            else if (remaining>1) begin
                                bytes<={bytes[7:0],8'b0}; byte_value<=bytes[15:8];
                                remaining<=remaining-1; bit_index<=7; state<=BIT_SETUP;
                            end else if (want_read) state<=RESTART_SETUP;
                            else state<=STOP_SETUP;
                        end
                        RESTART_SETUP: begin sda_low<=0; state<=RESTART_RISE; end
                        RESTART_RISE: begin scl_low<=0; state<=RESTART_HIGH; end
                        RESTART_HIGH: begin
                            byte_value<=address_read; read_address<=1;
                            bit_index<=7; state<=START_SDA;
                        end
                        READ_SETUP: begin sda_low<=0; state<=READ_RISE; end
                        READ_RISE: begin scl_low<=0; state<=READ_HIGH; end
                        READ_HIGH: begin rx[bit_index]<=sda_in; state<=READ_FALL; end
                        READ_FALL: begin
                            scl_low<=1;
                            if (bit_index==0) state<=NAK_SETUP;
                            else begin bit_index<=bit_index-1; state<=READ_SETUP; end
                        end
                        NAK_SETUP: begin sda_low<=0; state<=NAK_RISE; end
                        NAK_RISE: begin scl_low<=0; state<=NAK_HIGH; end
                        NAK_HIGH: state<=NAK_FALL;
                        NAK_FALL: begin scl_low<=1; state<=STOP_SETUP; end
                        STOP_SETUP: begin sda_low<=1; state<=STOP_RISE; end
                        STOP_RISE: begin scl_low<=0; state<=STOP_HIGH; end
                        STOP_HIGH: state<=STOP_RELEASE;
                        STOP_RELEASE: begin sda_low<=0; state<=STOP_DONE; end
                        STOP_DONE: begin
                            if (recovery_stop) begin recovery_stop<=0; state<=START_WAIT; end
                            else begin done<=1; state<=IDLE; end
                        end
                        CLEAR_LOW: begin scl_low<=1; sda_low<=0; state<=CLEAR_RISE; end
                        CLEAR_RISE: begin scl_low<=0; state<=CLEAR_HIGH; end
                        CLEAR_HIGH: state<=CLEAR_FALL;
                        CLEAR_FALL: begin
                            scl_low<=1;
                            if (recovery_clocks==8) begin recovery_stop<=1; state<=STOP_SETUP; end
                            else begin recovery_clocks<=recovery_clocks+1; state<=CLEAR_LOW; end
                        end
                        default: begin failed<=1; done<=1; scl_low<=0; sda_low<=0; state<=IDLE; end
                    endcase
                end
            end
        end
    end
endmodule
