`default_nettype none
// Nine-bit, MSB-first SPI; command/data is bit 8. The ROM is the published
// ModRetro ST7785 setup table. Explicit waits make reset and sleep-out timing
// independent of the remainder of the configuration table.
module panel_init #(
    parameter integer RESET_CYCLES = 1006633, // 30 ms at 33.554432 MHz
    parameter integer RELEASE_CYCLES = 671089, // 20 ms
    parameter integer SLEEP_CYCLES = 5033165, // 150 ms after sleep-out
    parameter integer HALF_SPI = 24,
    parameter INIT_FILE = "src/panel-init.bin"
)(
    input wire clk, reset,
    output reg lcd_reset, cs, sck, sda, done
);
    localparam RST=0, RELEASE=1, LOAD=2, RISE=3, FALL=4, GAP=5, SLEEP=6, FINISH=7;
    reg [2:0] state;
    reg [23:0] delay_count;
    reg [8:0] init_words [0:127];
    reg [8:0] shift;
    reg [6:0] index;
    reg [3:0] bit_count;
    initial $readmemb(INIT_FILE,init_words);
    always @(posedge clk) begin
        if(reset) begin
            lcd_reset<=0; cs<=1; sck<=0; sda<=0; done<=0;
            state<=RST; delay_count<=0; index<=0; bit_count<=0; shift<=0;
        end else case(state)
            RST: if({8'd0,delay_count}==RESET_CYCLES-1) begin
                lcd_reset<=1; delay_count<=0; state<=RELEASE;
            end else delay_count<=delay_count+1'b1;
            RELEASE: if({8'd0,delay_count}==RELEASE_CYCLES-1) begin
                delay_count<=0; state<=LOAD;
            end else delay_count<=delay_count+1'b1;
            LOAD: begin
                shift<=init_words[index]; sda<=init_words[index][8]; cs<=0; sck<=0;
                bit_count<=0; delay_count<=0; state<=RISE;
            end
            RISE: if({8'd0,delay_count}==HALF_SPI-1) begin
                sck<=1; delay_count<=0; state<=FALL;
            end else delay_count<=delay_count+1'b1;
            FALL: if({8'd0,delay_count}==HALF_SPI-1) begin
                sck<=0; delay_count<=0;
                if(bit_count==8) state<=GAP;
                else begin
                    shift<={shift[7:0],1'b0}; sda<=shift[7];
                    bit_count<=bit_count+1'b1; state<=RISE;
                end
            end else delay_count<=delay_count+1'b1;
            GAP: begin
                cs<=1; sda<=0;
                if({8'd0,delay_count}==HALF_SPI-1) begin
                    delay_count<=0;
                    if(index==0) begin index<=1; state<=SLEEP; end
                    else if(index==126) state<=FINISH;
                    else begin index<=index+1'b1; state<=LOAD; end
                end else delay_count<=delay_count+1'b1;
            end
            SLEEP: if({8'd0,delay_count}==SLEEP_CYCLES-1) begin
                delay_count<=0; state<=LOAD;
            end else delay_count<=delay_count+1'b1;
            FINISH: begin done<=1; cs<=1; sck<=0; end
            default: state<=RST;
        endcase
    end
endmodule
`default_nettype wire
