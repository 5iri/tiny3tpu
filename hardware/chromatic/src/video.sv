`default_nettype none
module video(input wire [7:0] x,y,
    input wire display_valid,paused,reverse,
    input wire [3:0] pixel,
    input wire [7:0] phase,
    input wire [2:0] speed,
    input wire [31:0] cycles,
    output reg [5:0] red,green,blue);
    `include "font.vh"
    function automatic [7:0] hexchar(input [3:0] n);
        hexchar=n<10?8'd48+{4'b0,n}:8'd55+{4'b0,n};
    endfunction
    reg [7:0] ch,col;
    reg [2:0] gx,gy;
    reg [14:0] bits;
    reg text_on;
    always @* begin
        red=2;green=3;blue=7;
        if(display_valid && pixel!=0) begin
            red=6'd30+{2'b0,pixel}*6'd2;
            green=6'd8+{2'b0,pixel}*6'd3;
            blue=2;
        end
        ch=32;col=(x-4)>>2;gx={1'b0,x[1:0]};gy=0;text_on=0;
        if(y<17 || y>=127) begin red=4;green=6;blue=11;end
        if(y==16 || y==127)begin red=16;green=19;blue=20;end
        if(x>=4 && x<156)begin
            if(y>=4 && y<9)begin
                text_on=1;gy=3'(y-4);
                case(col)
                    0:ch="T";1:ch="I";2:ch="N";3:ch="Y";4:ch="3";5:ch="T";6:ch="P";7:ch="U";
                    11:ch="/";15:ch="F";16:ch="P";17:ch="G";18:ch="A";
                    23:ch="B";24:ch="A";25:ch="N";26:ch="A";27:ch="N";28:ch="A";
                    33:ch="4";34:ch="X";35:ch="4";
                    default:ch=32;
                endcase
            end else if(y>=130 && y<135)begin
                text_on=1;gy=3'(y-130);
                case(col)
                    0:ch="A";1:ch=":";2:ch=paused?"P":"R";3:ch=paused?"A":"U";4:ch=paused?"U":"N";
                    5:ch=paused?"S":" ";6:ch=paused?"E":" ";
                    9:ch="B";10:ch=":";11:ch=reverse?"R":"F";12:ch=reverse?"E":"W";13:ch=reverse?"V":"D";
                    17:ch="S";18:ch="P";19:ch="D";20:ch=8'd48+{5'b0,speed};
                    25:ch="R";26:ch="O";27:ch="T";28:ch=hexchar(phase[7:4]);29:ch=hexchar(phase[3:0]);
                    default:ch=32;
                endcase
            end else if(y>=138 && y<143)begin
                text_on=1;gy=3'(y-138);
                case(col)
                    0:ch="C";1:ch="Y";2:ch="C";
                    15:ch="2";16:ch="0";17:ch="4";19:ch="V";20:ch="E";21:ch="R";22:ch="T";
                    26:ch="5";27:ch="1";29:ch="G";30:ch="E";31:ch="M";32:ch="M";
                    default:if(col>=4 && col<12)ch=hexchar(cycles[(11-col)*4+:4]);
                endcase
            end
        end
        bits=glyph(ch);
        if(text_on && gx<3 && bits[14-(gy*3+gx)])begin red=60;green=57;blue=39;end
    end
endmodule
`default_nettype wire
