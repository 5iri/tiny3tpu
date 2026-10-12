`default_nettype none
`include "mesh_config.vh"
// Native 640x480, two candidate pixels per clock. The depth read and commit
// stages overlap; each triangle visits each pair once, and a drain cycle
// commits its last pair before the next face can read the same location.
module kc705_hdmi_renderer #(parameter CPU_DRIVEN=0, parameter PIXEL_BITS=CPU_DRIVEN ? 6 : 4)(
    input wire clk, reset, start,
    input wire [7:0] phase,
    input wire vertex_write,
    input wire [11:0] vertex_index,
    input wire [27:0] vertex_data,
    output wire busy,
    output reg done,
    output wire write_enable,
    output wire [17:0] write_address,
    output wire [1:0] write_mask,
    output wire [2*PIXEL_BITS-1:0] write_data
);
    localparam VERTEX_BITS=CPU_DRIVEN ? `HDMI_VERTEX_BITS : 8, FACE_BITS=CPU_DRIVEN ? `HDMI_FACE_BITS : 9;
    localparam TRIANGLES=CPU_DRIVEN ? `HDMI_TRIANGLES : 407;
    localparam FACE_WIDTH=3*VERTEX_BITS+(CPU_DRIVEN ? 3*PIXEL_BITS : PIXEL_BITS);
    localparam IDLE=0, CLEAR=1, LOAD_B=2, LOAD_A=3, LAUNCH=4, WAIT_TPU=5,
        READ_X=6, READ_Y=7, READ_Z=8, FACE=9, FACE_WAIT=10,
        V0_WAIT=11, V0=12, V1_WAIT=13, V1=14, V2_WAIT=15, V2=16,
        BOUNDS=17, EDGES=18, PIXEL=19, DRAIN=20, NEXT_FACE=22;
    reg [4:0] state;
    reg [7:0] angle, base_vertex;
    reg [3:0] load_index;
    reg [1:0] result_row;
    reg [17:0] clear_address;
    reg [FACE_BITS-1:0] face_index;
    reg [9:0] sx,sy;
    reg [9:0] vx0,vy0,vx1,vy1,vx2,vy2;
    reg [7:0] vz0,vz1,vz2;
    reg [9:0] xmin,xmax,ymin,ymax,px,py;
    reg [7:0] depth_value;
    reg [3:0] shade;
    reg [PIXEL_BITS-1:0] shade0,shade1,shade2;
    reg signed [23:0] area;
    reg signed [27:0] light_value,light_row,light_dx,light_dy;
    reg signed [23:0] e0,e1,e2,row0,row1,row2;
    reg signed [11:0] dx0,dy0,dx1,dy1,dx2,dy2;
    reg signed [7:0] vertices [0:1023];
    reg signed [7:0] rotations [0:4095];
    // The denser CPU face ROM uses BRAM; retain the small standalone ROM in LUTs.
    (* ram_style=CPU_DRIVEN ? "block" : "logic" *) reg [FACE_WIDTH-1:0] faces [0:(1<<FACE_BITS)-1];
    reg [FACE_WIDTH-1:0] face_q;
    (* ram_style="block", no_rw_check *) reg [27:0] projected [0:(1<<VERTEX_BITS)-1];
    reg [VERTEX_BITS-1:0] vertex_address;
    reg [27:0] vertex_q;
    wire [15:0] depth_q;
    wire [17:0] pixel_address=({8'b0,py}<<8)+({8'b0,py}<<6)+{9'b0,px[9:1]};
    wire signed [23:0] e0_right=e0-{{12{dy0[11]}},dy0};
    wire signed [23:0] e1_right=e1-{{12{dy1[11]}},dy1};
    wire signed [23:0] e2_right=e2-{{12{dy2[11]}},dy2};
    function automatic inside_edges(input signed [23:0] a,b,c);
        inside_edges=(!a[23] && !b[23] && !c[23]) || (a<=0 && b<=0 && c<=0);
    endfunction
    reg pending;
    reg [1:0] pending_inside;
    reg [17:0] pending_address;
    reg [7:0] pending_depth;
    reg [2*PIXEL_BITS-1:0] pending_shade;
    wire [1:0] hits={pending && pending_inside[1] && pending_depth<depth_q[15:8],
                     pending && pending_inside[0] && pending_depth<depth_q[7:0]};
    assign busy=(state!=IDLE);
    assign write_enable=!reset && ((state==CLEAR) || (|hits));
    assign write_mask=(state==CLEAR) ? 2'b11 : hits;
    assign write_address=(state==CLEAR) ? clear_address : pending_address;
    assign write_data=(state==CLEAR) ? {2*PIXEL_BITS{1'b0}} : pending_shade;
    // Barycentric light is linear across the triangle. Only its numerator
    // increments per pixel. Six compare/subtract stages quantize to the
    // 64-entry palette, avoiding a variable-width hardware divider.
    // Shift/add the small light coefficient explicitly. DSP input-register
    // absorption creates profiles not covered by this nextpnr timing model.
    function automatic signed [27:0] scale_light(input signed [23:0] value,input [PIXEL_BITS-1:0] coefficient);
        reg signed [27:0] v,p0,p1,p2;
        reg [5:0] s;
        begin
            v={{4{value[23]}},value};s=6'(coefficient);
            p0=(s[0] ? v : 28'sd0)+(s[1] ? (v<<1) : 28'sd0);
            p1=(s[2] ? (v<<2) : 28'sd0)+(s[3] ? (v<<3) : 28'sd0);
            p2=(s[4] ? (v<<4) : 28'sd0)+(s[5] ? (v<<5) : 28'sd0);
            scale_light=(p0+p1)+p2;
        end
    endfunction
    function automatic signed [27:0] weighted(input signed [23:0] a,b,c);
        weighted=scale_light(a,shade2)+scale_light(b,shade0)+scale_light(c,shade1);
    endfunction
    function automatic [PIXEL_BITS-1:0] shade_at(input signed [27:0] numerator,input signed [23:0] signed_area);
        reg signed [27:0] oriented;
        reg [27:0] remainder,denominator;
        integer bit_index;
        begin
            oriented=signed_area[23] ? -numerator : numerator;
            denominator=signed_area[23] ? 28'(-signed_area) : 28'(signed_area);
            remainder=oriented<0 ? 0 : $unsigned(oriented)+(denominator>>1);
            shade_at=0;
            for(bit_index=PIXEL_BITS-1;bit_index>=0;bit_index=bit_index-1)begin
                if(denominator!=0 && remainder>=(denominator<<bit_index))begin
                    remainder=remainder-(denominator<<bit_index);shade_at[bit_index]=1;
                end
            end
        end
    endfunction
    // Candidate metadata is delayed by the same cycle as the synchronous Z
    // read. Writes use the delayed address, never the next candidate address.
    always @(posedge clk) begin
        if(reset) begin
            pending<=0;pending_inside<=0;pending_address<=0;pending_depth<=0;pending_shade<=0;
        end else begin
            pending<=state==PIXEL;
            if(state==PIXEL) begin
                pending_inside<={inside_edges(e0_right,e1_right,e2_right) && px+10'd1<=xmax,
                                 inside_edges(e0,e1,e2) && px>=xmin};
                pending_address<=pixel_address;pending_depth<=depth_value;
                pending_shade<=CPU_DRIVEN ? {shade_at(light_value+light_dx,area),shade_at(light_value,area)} : {PIXEL_BITS'(shade),PIXEL_BITS'(shade)};
            end
        end
    end
    initial begin
        $readmemh("assets/vertices.hex",vertices);
        $readmemh("assets/rotations.hex",rotations);
        if(CPU_DRIVEN)$readmemh("../kc705_hdmi/assets/faces.hex",faces);
        else $readmemh("assets/faces.hex",faces);
    end
    wire core_busy,core_done;
    wire read_result=(state==READ_X || state==READ_Y || state==READ_Z);
    wire [1:0] result_col=(state==READ_X)?2'd0:(state==READ_Y)?2'd1:2'd2;
    wire signed [31:0] result;
    wire [9:0] operand_address={base_vertex,2'b00}+{6'b0,load_index};
    wire signed [7:0] operand=(state==LOAD_B)?rotations[{angle,load_index}]:vertices[operand_address];
    generate if(!CPU_DRIVEN)begin: standalone_transform
    tpu_core_wrapper #(.N(4),.DW(8),.CW(32)) tpu(
        .clk(clk),.rst(reset),.start(state==LAUNCH),.continue_accum(1'b0),
        .busy(core_busy),.done(core_done),
        .load_en(state==LOAD_A || state==LOAD_B),.load_sel(state==LOAD_B),
        .load_row(load_index[3:2]),.load_col(load_index[1:0]),.load_data(operand),
        .c_rd_en(read_result),.c_rd_row(result_row),.c_rd_col(result_col),.c_rd_data(result)
    );
    end else begin: cpu_transform
        assign result=0;assign core_busy=0;assign core_done=0;
    end endgenerate
    function automatic [9:0] min3(input [9:0] a,b,c);
        min3=(a<b)?((a<c)?a:c):((b<c)?b:c);
    endfunction
    function automatic [9:0] max3(input [9:0] a,b,c);
        max3=(a>b)?((a>c)?a:c):((b>c)?b:c);
    endfunction
    function automatic signed [11:0] difference(input [9:0] a,b);
        difference=$signed({2'b0,a})-$signed({2'b0,b});
    endfunction
    function automatic signed [23:0] edge_at(input [9:0] ax,ay,bx,by,x,y);
        edge_at=difference(bx,ax)*difference(y,ay)-difference(by,ay)*difference(x,ax);
    endfunction
    // Synchronous face/vertex memories; depth reads are pipelined separately.
    always @(posedge clk) begin
        face_q<=faces[face_index];
        vertex_q<=projected[vertex_address];
        if(CPU_DRIVEN)begin
            if(vertex_write && !busy)projected[vertex_index[VERTEX_BITS-1:0]]<=vertex_data;
        end else if(state==READ_Z) projected[VERTEX_BITS'(base_vertex)+VERTEX_BITS'(result_row)]<=
                {8'(32'sd128+(result>>>7)),sy,sx};

    end
    kc705_hdmi_ram #(.WIDTH(8)) depth_memory(
        .clk(clk),.write_enable(write_enable),.write_mask(write_mask),
        .write_address(write_address),
        .write_data(state==CLEAR ? 16'hffff : {pending_depth,pending_depth}),
        .read_address(pixel_address),.read_data(depth_q));
    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE;done<=0;angle<=0;base_vertex<=0;load_index<=0;result_row<=0;
            clear_address<=0;face_index<=0;vertex_address<=0;sx<=0;sy<=0;
            vx0<=0;vy0<=0;vz0<=0;vx1<=0;vy1<=0;vz1<=0;vx2<=0;vy2<=0;vz2<=0;
            xmin<=0;xmax<=0;ymin<=0;ymax<=0;px<=0;py<=0;depth_value<=0;shade<=0;
            shade0<=0;shade1<=0;shade2<=0;area<=0;
            light_value<=0;light_row<=0;light_dx<=0;light_dy<=0;
            e0<=0;e1<=0;e2<=0;row0<=0;row1<=0;row2<=0;
            dx0<=0;dy0<=0;dx1<=0;dy1<=0;dx2<=0;dy2<=0;
        end else begin
            done<=0;
            case(state)
                IDLE: if(start) begin angle<=phase;clear_address<=0;state<=CLEAR;end
                CLEAR: if(clear_address==153599) begin
                           load_index<=0;face_index<=0;state<=CPU_DRIVEN ? FACE : LOAD_B;
                       end
                       else clear_address<=clear_address+1'b1;
                LOAD_B: if(load_index==15) begin load_index<=0;base_vertex<=0;state<=LOAD_A;end
                        else load_index<=load_index+1'b1;
                LOAD_A: if(load_index==15) begin load_index<=0;state<=LAUNCH;end
                        else load_index<=load_index+1'b1;
                LAUNCH: state<=WAIT_TPU;
                WAIT_TPU: if(core_done) begin result_row<=0;state<=READ_X;end
                READ_X: begin sx<=10'(32'sd320+(result>>>6));state<=READ_Y;end
                READ_Y: begin sy<=10'(32'sd280-(result>>>6));state<=READ_Z;end
                READ_Z: if(result_row==3) begin
                    if(base_vertex==200) begin face_index<=0;state<=FACE;end
                    else begin base_vertex<=base_vertex+4;state<=LOAD_A;end
                end else begin result_row<=result_row+1'b1;state<=READ_X;end
                FACE: state<=FACE_WAIT;
                FACE_WAIT: begin
                    vertex_address<=face_q[0+:VERTEX_BITS];shade<=face_q[3*VERTEX_BITS+:4];
                    if(CPU_DRIVEN)begin
                        shade0<=face_q[3*VERTEX_BITS+:PIXEL_BITS];
                        shade1<=face_q[(CPU_DRIVEN ? 3*VERTEX_BITS+PIXEL_BITS : 3*VERTEX_BITS)+:PIXEL_BITS];
                        shade2<=face_q[(CPU_DRIVEN ? 3*VERTEX_BITS+2*PIXEL_BITS : 3*VERTEX_BITS)+:PIXEL_BITS];
                    end
                    state<=V0_WAIT;
                end
                V0_WAIT: state<=V0;
                V0: begin {vz0,vy0,vx0}<=vertex_q;vertex_address<=face_q[VERTEX_BITS+:VERTEX_BITS];state<=V1_WAIT;end
                V1_WAIT: state<=V1;
                V1: begin {vz1,vy1,vx1}<=vertex_q;vertex_address<=face_q[2*VERTEX_BITS+:VERTEX_BITS];state<=V2_WAIT;end
                V2_WAIT: state<=V2;
                V2: begin {vz2,vy2,vx2}<=vertex_q;state<=BOUNDS;end
                BOUNDS: begin
                    xmin<=min3(vx0,vx1,vx2);xmax<=max3(vx0,vx1,vx2);
                    ymin<=min3(vy0,vy1,vy2);ymax<=max3(vy0,vy1,vy2);
                    depth_value<=8'(({2'b0,vz0}+{2'b0,vz1}+{2'b0,vz2})/10'd3);
                    dx0<=difference(vx1,vx0);dy0<=difference(vy1,vy0);
                    dx1<=difference(vx2,vx1);dy1<=difference(vy2,vy1);
                    dx2<=difference(vx0,vx2);dy2<=difference(vy0,vy2);
                    area<=edge_at(vx0,vy0,vx1,vy1,vx2,vy2);
                    if(edge_at(vx0,vy0,vx1,vy1,vx2,vy2)==0) state<=NEXT_FACE;
                    else state<=EDGES;
                end
                EDGES: begin
                    px<={xmin[9:1],1'b0};py<=ymin;
                    light_value<=weighted(edge_at(vx0,vy0,vx1,vy1,{xmin[9:1],1'b0},ymin),
                        edge_at(vx1,vy1,vx2,vy2,{xmin[9:1],1'b0},ymin),edge_at(vx2,vy2,vx0,vy0,{xmin[9:1],1'b0},ymin));
                    light_row<=weighted(edge_at(vx0,vy0,vx1,vy1,{xmin[9:1],1'b0},ymin),
                        edge_at(vx1,vy1,vx2,vy2,{xmin[9:1],1'b0},ymin),edge_at(vx2,vy2,vx0,vy0,{xmin[9:1],1'b0},ymin));
                    light_dx<=weighted(-(24'(dy0)),-(24'(dy1)),-(24'(dy2)));
                    light_dy<=weighted(24'(dx0),24'(dx1),24'(dx2));
                    e0<=edge_at(vx0,vy0,vx1,vy1,{xmin[9:1],1'b0},ymin);row0<=edge_at(vx0,vy0,vx1,vy1,{xmin[9:1],1'b0},ymin);
                    e1<=edge_at(vx1,vy1,vx2,vy2,{xmin[9:1],1'b0},ymin);row1<=edge_at(vx1,vy1,vx2,vy2,{xmin[9:1],1'b0},ymin);
                    e2<=edge_at(vx2,vy2,vx0,vy0,{xmin[9:1],1'b0},ymin);row2<=edge_at(vx2,vy2,vx0,vy0,{xmin[9:1],1'b0},ymin);
                    state<=PIXEL;
                end
                PIXEL: if(px[9:1]==xmax[9:1]) begin
                    if(py==ymax) state<=DRAIN;
                    else begin
                        px<={xmin[9:1],1'b0};py<=py+1'b1;
                        light_row<=light_row+light_dy;light_value<=light_row+light_dy;
                        row0<=row0+{{12{dx0[11]}},dx0};e0<=row0+{{12{dx0[11]}},dx0};
                        row1<=row1+{{12{dx1[11]}},dx1};e1<=row1+{{12{dx1[11]}},dx1};
                        row2<=row2+{{12{dx2[11]}},dx2};e2<=row2+{{12{dx2[11]}},dx2};
                    end
                end else begin
                    light_value<=light_value+(light_dx<<1);
                    px<=px+10'd2;e0<=e0-({{12{dy0[11]}},dy0}<<1);
                    e1<=e1-({{12{dy1[11]}},dy1}<<1);e2<=e2-({{12{dy2[11]}},dy2}<<1);
                end
                DRAIN: state<=NEXT_FACE;
                NEXT_FACE: if(face_index==FACE_BITS'(TRIANGLES-1)) begin done<=1;state<=IDLE;end
                           else begin face_index<=face_index+1'b1;state<=FACE;end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
