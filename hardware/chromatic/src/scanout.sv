`default_nettype none
// Derived from the board timing constants in ModRetro's ST7785_panel_master.
// One RGB666 pixel occupies three dot clocks. The panel controller scans 240
// columns; the physical 160-column window begins at the documented offset 41.
// All logic is synchronous to clk; there are no generated internal clocks.
module scanout(
    input wire clk,reset,enable,
    input wire [5:0] red,green,blue,
    output wire [7:0] x,y,
    output wire frame_tick,
    output wire dotclk,
    output reg de,hsync,vsync,
    output reg [5:0] data
);
    reg [1:0] divider;
    reg [9:0] h;
    reg [7:0] v, column;
    reg [1:0] component;
    wire ce=(divider==1);
    wire active=(h>=64 && h<784 && v>=4 && v<148);
    wire visible=(column>=41 && column<201);
    assign x=column-41;
    assign y=v-4;
    assign dotclk=divider[1];
    assign frame_tick=ce && h==911 && v==157;
    always @(posedge clk) begin
        if(reset) begin
            divider<=0;h<=0;v<=0;column<=0;component<=0;
            de<=0;hsync<=0;vsync<=0;data<=0;
        end else begin
            divider<=divider+1'b1;
            if(ce) begin
                if(h==911) begin h<=0;v<=(v==157)?0:v+1'b1; end
                else h<=h+1'b1;
                hsync<=h>=30; vsync<=v>=2; de<=active;
                if(h<64 || h>=784) begin column<=0;component<=0; end
                else if(component==2) begin component<=0;column<=column+1'b1; end
                else component<=component+1'b1;
                data<=0;
                if(enable && active && visible) case(component)
                    0:data<=red;
                    1:data<=green;
                    2:data<=blue;
                    default:data<=0;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
