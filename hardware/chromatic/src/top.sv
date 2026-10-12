`default_nettype none
module top(
    input wire CLK_FPGA, POWER_ON_FPGA,
    input wire BTN_A, BTN_B, BTN_DPAD_UP, BTN_DPAD_DOWN,
    input wire BTN_DPAD_LEFT, BTN_DPAD_RIGHT, BTN_START, BTN_SEL,
    output wire [5:0] LCD_DB,
    output wire LCD_DOTCLK,LCD_ENABLE,LCD_HSYNC,LCD_VSYNC,
    output wire LCD_RESET,LCD_SPI_CSX,LCD_SPI_SCLK,LCD_SPI_SDA,LCD_PWM,
    output wire FPGA_LED_EN,FPGA_LED_R,FPGA_LED_G,FPGA_LED_B,
    output wire AUD_RESET,AUD_BCLK,AUD_DIN,AUD_MCLK,AUD_WCLK,
    output wire ESP32_EN,ESP32_IO0,
    output wire CART_PWR_EN,CART_CTRL_OE,CART_DATA_DIR_E,
    output wire CART_CLK,CART_CS,CART_RD,CART_WR,
    output wire [15:0] CART_A,
    inout wire [7:0] CART_D,
    inout wire CART_RST,
    output wire PS_CE_N,PS_CLK,
    inout wire [7:0] PS_DQ,
    inout wire PS_DQS,
    output wire LINK_CLK_DIR_LV,LINK_SD_DIR_LV,
    inout wire LINK_CLK,
    output wire LINK_OUT,IR_LED,SDIO_LS,CHG_EN_FPGA,usb_pullup_en_o,
    inout wire POWER_DOWN_IO,SCL,SDA
);
    // nextpnr's Gowin packer uses this net attribute to allocate a dedicated
    // global-clock entry point (GW5A has no user-instantiable BUFG primitive).
    (* CLOCK = "true", keep = 1 *) wire clk;
    assign clk=CLK_FPGA;
    reg [15:0] por=0;
    wire reset=!(&por);
    always @(posedge clk) if(!(&por)) por<=por+1'b1;
    (* async_reg="true" *) reg off1=1,off2=1;
    always @(posedge clk) begin off1<=POWER_ON_FPGA;off2<=off1;end
    wire [7:0] held,pressed,x,y,phase,display_phase;
    wire frame_tick,initialized,render_start,render_done,busy,display_valid,display_bank;
    wire write_enable,paused,reverse;
    wire [2:0] speed;
    wire [14:0] write_address;
    wire [14:0] read_address=(x<160 && y<144)?({7'b0,y}<<7)+({7'b0,y}<<5)+{7'b0,x}:15'd0;
    wire [3:0] write_data,pixel;
    wire [31:0] cycles;
    wire [15:0] frames;
    wire [5:0] red,green,blue;
    buttons u_buttons(clk,reset,
        {BTN_SEL,BTN_START,BTN_DPAD_RIGHT,BTN_DPAD_LEFT,BTN_DPAD_DOWN,BTN_DPAD_UP,BTN_B,BTN_A},held,pressed);
    scene u_scene(clk,reset,frame_tick,render_done,held,pressed,render_start,
        display_bank,display_valid,phase,display_phase,paused,reverse,speed,cycles,frames);
    banana_renderer u_renderer(clk,reset,render_start,phase,busy,render_done,
        write_enable,write_address,write_data);
    framebuffer u_framebuffer(clk,write_enable,{!display_bank,write_address},write_data,
        display_bank,read_address,pixel);
    video u_video(x,y,display_valid,paused,reverse,pixel,display_phase,speed,cycles,red,green,blue);
    panel_init u_init(clk,reset,LCD_RESET,LCD_SPI_CSX,LCD_SPI_SCLK,LCD_SPI_SDA,initialized);
    scanout u_scan(clk,reset,initialized&&!off2,red,green,blue,x,y,frame_tick,
        LCD_DOTCLK,LCD_ENABLE,LCD_HSYNC,LCD_VSYNC,LCD_DB);
    reg [7:0] pwm=0;
    reg [24:0] warmup=0;
    always @(posedge clk) begin
        pwm<=pwm+1'b1;
        if(!warmup[24]) warmup<=warmup+1'b1;
    end
    assign LCD_PWM=initialized && warmup[24] && !off2 && pwm[7:0]<64;
    assign FPGA_LED_EN=!off2;
    assign FPGA_LED_R=1;
    assign FPGA_LED_G=!display_valid;
    assign FPGA_LED_B=!busy;
    // Peripherals outside this demo are held inactive. Cartridge data/reset
    // and link/I2C lines are high impedance. No cartridge transaction occurs.
    assign AUD_RESET=0;
    assign {AUD_BCLK,AUD_DIN,AUD_MCLK,AUD_WCLK}=0;
    assign ESP32_EN=0; assign ESP32_IO0=1;
    assign CART_PWR_EN=0; assign CART_CTRL_OE=0; assign CART_DATA_DIR_E=0;
    assign CART_A=0; assign {CART_CLK,CART_CS,CART_RD,CART_WR}=4'b1111;
    assign CART_D=8'bz;assign CART_RST=1'bz;
    assign PS_CE_N=1;assign PS_CLK=0;assign PS_DQ=8'bz;assign PS_DQS=1'bz;
    assign LINK_CLK_DIR_LV=0;assign LINK_SD_DIR_LV=0;assign LINK_CLK=1'bz;
    assign LINK_OUT=0;assign IR_LED=0;assign SDIO_LS=1;
    // Match the reference board's static charger-enable level; the existing
    // external PMIC owns charge management. This demo performs no PMIC writes.
    assign CHG_EN_FPGA=1;
    assign usb_pullup_en_o=0;
    assign POWER_DOWN_IO=1'bz;assign SCL=1'bz;assign SDA=1'bz;
endmodule
`default_nettype wire
