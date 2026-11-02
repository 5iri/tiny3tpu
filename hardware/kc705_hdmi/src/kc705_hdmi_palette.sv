`default_nettype none
`include "mesh_config.vh"
// Native 640x480 typography over a native 640x480 live-rendered object.
module kc705_hdmi_palette #(parameter CPU_DRIVEN=0)(
    input wire [9:0] x,
    input wire [8:0] y,
    input wire display_valid,
    input wire [(CPU_DRIVEN ? 6 : 4)-1:0] pixel,
    output reg [5:0] red,green,blue
);
    `include "font.vh"
    reg [7:0] ch;
    reg [14:0] bits;
    integer col,gx,gy;
    reg title,text_on;
    always @* begin
        red=6'd3+{4'd0,y[8:7]};
        green=6'd4+{4'd0,y[8:7]};
        blue=6'd7+{3'd0,y[8:6]};
        if(display_valid && pixel!=0) begin
            if(CPU_DRIVEN)case(6'(pixel))
                0:begin red=24;green=12;blue=1;end
                1:begin red=24;green=12;blue=1;end
                2:begin red=24;green=12;blue=1;end
                3:begin red=24;green=12;blue=1;end
                4:begin red=24;green=12;blue=1;end
                5:begin red=24;green=12;blue=1;end
                6:begin red=24;green=12;blue=1;end
                7:begin red=24;green=12;blue=1;end
                8:begin red=24;green=12;blue=1;end
                9:begin red=24;green=12;blue=1;end
                10:begin red=24;green=12;blue=1;end
                11:begin red=24;green=12;blue=1;end
                12:begin red=24;green=12;blue=1;end
                13:begin red=26;green=13;blue=1;end
                14:begin red=27;green=14;blue=1;end
                15:begin red=29;green=15;blue=1;end
                16:begin red=30;green=16;blue=1;end
                17:begin red=32;green=17;blue=1;end
                18:begin red=33;green=19;blue=1;end
                19:begin red=35;green=20;blue=1;end
                20:begin red=36;green=21;blue=1;end
                21:begin red=38;green=23;blue=1;end
                22:begin red=39;green=24;blue=2;end
                23:begin red=41;green=26;blue=2;end
                24:begin red=42;green=27;blue=2;end
                25:begin red=43;green=29;blue=2;end
                26:begin red=44;green=30;blue=2;end
                27:begin red=45;green=32;blue=2;end
                28:begin red=46;green=33;blue=2;end
                29:begin red=47;green=35;blue=2;end
                30:begin red=48;green=36;blue=3;end
                31:begin red=49;green=38;blue=3;end
                32:begin red=50;green=39;blue=3;end
                33:begin red=51;green=40;blue=3;end
                34:begin red=52;green=41;blue=4;end
                35:begin red=53;green=42;blue=4;end
                36:begin red=54;green=43;blue=4;end
                37:begin red=55;green=44;blue=5;end
                38:begin red=56;green=45;blue=5;end
                39:begin red=56;green=46;blue=6;end
                40:begin red=57;green=47;blue=6;end
                41:begin red=58;green=48;blue=7;end
                42:begin red=58;green=49;blue=8;end
                43:begin red=59;green=49;blue=8;end
                44:begin red=59;green=50;blue=9;end
                45:begin red=60;green=51;blue=10;end
                46:begin red=60;green=52;blue=11;end
                47:begin red=61;green=52;blue=11;end
                48:begin red=61;green=53;blue=12;end
                49:begin red=61;green=54;blue=13;end
                50:begin red=62;green=55;blue=14;end
                51:begin red=62;green=55;blue=15;end
                52:begin red=62;green=56;blue=16;end
                53:begin red=62;green=57;blue=18;end
                54:begin red=63;green=58;blue=19;end
                55:begin red=63;green=58;blue=21;end
                56:begin red=63;green=59;blue=22;end
                57:begin red=63;green=60;blue=24;end
                58:begin red=63;green=60;blue=26;end
                59:begin red=63;green=61;blue=27;end
                60:begin red=63;green=61;blue=29;end
                61:begin red=63;green=61;blue=29;end
                62:begin red=63;green=61;blue=29;end
                63:begin red=63;green=61;blue=29;end
                default:begin red=63;green=61;blue=29;end
            endcase
            else case(pixel)
                1,2,3:begin red=24;green=12;blue=1;end
                4:begin red=30;green=16;blue=1;end
                5:begin red=36;green=21;blue=1;end
                6:begin red=42;green=27;blue=2;end
                7:begin red=46;green=33;blue=2;end
                8:begin red=50;green=39;blue=3;end
                9:begin red=54;green=43;blue=4;end
                10:begin red=57;green=47;blue=6;end
                11:begin red=59;green=50;blue=9;end
                12:begin red=61;green=53;blue=12;end
                13:begin red=62;green=56;blue=16;end
                14:begin red=63;green=59;blue=22;end
                default:begin red=63;green=61;blue=29;end
            endcase
        end
        if((y==65 || y==420) && x>=32 && x<608) begin
            red=12;green=15;blue=20;
        end
        ch=32;col=0;gx=0;gy=0;text_on=0;title=0;
        if(y>=28 && y<43 && x>=32 && x<128) begin
            title=1;text_on=1;col=(int'(x)-32)/12;
            gx=((int'(x)-32)%12)/3;gy=(int'(y)-28)/3;
            case(col)
                0:ch="T";1:ch="I";2:ch="N";3:ch="Y";
                4:ch="3";5:ch="T";6:ch="P";7:ch="U";
                default:ch=32;
            endcase
        end else if(y>=33 && y<43 && x>=520 && x<608) begin
            text_on=1;col=(int'(x)-520)/8;gx=((int'(x)-520)%8)/2;gy=(int'(y)-33)/2;
            if(CPU_DRIVEN)case(col)
                0:ch="J";1:ch="A";2:ch="X";4:ch="C";5:ch="P";6:ch="U";
                8:ch="T";9:ch="P";10:ch="U";
                default:ch=32;
            endcase
            else case(col)
                0:ch="R";1:ch="E";2:ch="A";3:ch="L";4:ch="T";
                5:ch="I";6:ch="M";7:ch="E";9:ch="3";10:ch="D";
                default:ch=32;
            endcase
        end else if((y>=435 && y<445 || y>=454 && y<464) && x>=32 && x<608) begin
            text_on=1;col=(int'(x)-32)/8;gx=((int'(x)-32)%8)/2;
            gy=y<445 ? (int'(y)-435)/2 : (int'(y)-454)/2;
            if(y<445 && CPU_DRIVEN) case(col)
                0:ch=8'(48+`HDMI_TRIANGLES/1000);1:ch=8'(48+(`HDMI_TRIANGLES/100)%10);
                2:ch=8'(48+(`HDMI_TRIANGLES/10)%10);3:ch=8'(48+`HDMI_TRIANGLES%10);5:ch="T";6:ch="R";7:ch="I";
                8:ch="A";9:ch="N";10:ch="G";11:ch="L";12:ch="E";13:ch="S";
                24:ch=8'(48+`HDMI_VERTICES/1000);25:ch=8'(48+(`HDMI_VERTICES/100)%10);
                26:ch=8'(48+(`HDMI_VERTICES/10)%10);27:ch=8'(48+`HDMI_VERTICES%10);
                29:ch="V";30:ch="E";31:ch="R";32:ch="T";33:ch="I";34:ch="C";35:ch="E";36:ch="S";
                65:ch="O";66:ch="N";68:ch="F";69:ch="P";70:ch="G";71:ch="A";
                default:ch=32;
            endcase
            else if(y<445) case(col)
                0:ch="4";1:ch="0";2:ch="7";4:ch="T";5:ch="R";6:ch="I";
                7:ch="A";8:ch="N";9:ch="G";10:ch="L";11:ch="E";12:ch="S";
                24:ch="2";25:ch="0";26:ch="4";28:ch="V";29:ch="E";
                30:ch="R";31:ch="T";32:ch="I";33:ch="C";34:ch="E";35:ch="S";
                65:ch="O";66:ch="N";68:ch="F";69:ch="P";70:ch="G";71:ch="A";
                default:ch=32;
            endcase
            else case(col)
                0:ch=CPU_DRIVEN?"2":"4";1:ch="X";2:ch="4";3:ch=CPU_DRIVEN?"X":" ";
                4:ch=CPU_DRIVEN?"4":"T";5:ch=CPU_DRIVEN?" ":"P";6:ch=CPU_DRIVEN?"T":"U";
                7:ch=CPU_DRIVEN?"P":" ";8:ch=CPU_DRIVEN?"U":" ";
                24:ch="6";25:ch="4";26:ch="0";27:ch="X";28:ch="4";29:ch="8";30:ch="0";
                32:ch="R";33:ch="E";34:ch="N";35:ch="D";36:ch="E";37:ch="R";
                63:ch="6";64:ch="0";65:ch="H";66:ch="Z";68:ch="H";69:ch="D";70:ch="M";71:ch="I";
                default:ch=32;
            endcase
        end
        bits=glyph(ch);
        if(text_on && gx<3 && bits[14-(gy*3+gx)]) begin
            if(title) begin red=63;green=57;blue=26;end
            else begin red=39;green=43;blue=49;end
        end
    end
endmodule
`default_nettype wire
