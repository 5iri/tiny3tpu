`default_nettype none
module banana_renderer(
    input wire clk, reset, start,
    input wire [7:0] phase,
    output wire busy,
    output reg done,
    output wire write_enable,
    output wire [14:0] write_address,
    output wire [3:0] write_data
);
    localparam IDLE=0, CLEAR=1, LOAD_B=2, LOAD_A=3, LAUNCH=4, WAIT_TPU=5,
        READ_X=6, READ_Y=7, READ_Z=8, FACE=9, FACE_WAIT=10,
        V0_WAIT=11, V0=12, V1_WAIT=13, V1=14, V2_WAIT=15, V2=16,
        BOUNDS=17, EDGES=18, PIXEL=19, DEPTH=20, ADVANCE=21, NEXT_FACE=22;
    reg [4:0] state;
    reg [7:0] angle, base_vertex;
    reg [3:0] load_index;
    reg [1:0] result_row;
    reg [14:0] clear_address;
    reg [8:0] face_index;
    reg [7:0] sx,sy;
    reg [7:0] vx0,vy0,vz0,vx1,vy1,vz1,vx2,vy2,vz2;
    reg [7:0] xmin,xmax,ymin,ymax,px,py;
    reg [7:0] depth_value;
    reg [3:0] shade;
    reg signed [19:0] e0,e1,e2,row0,row1,row2;
    reg signed [9:0] dx0,dy0,dx1,dy1,dx2,dy2;
    reg signed [7:0] vertices [0:1023];
    reg signed [7:0] rotations [0:4095];
    // Keep this small ROM in logic: the GW5A single-port ROM mapping failed
    // routed hold checks on its address pins. Frame/depth/vertex RAM stay BRAM.
    (* ram_style="logic" *) reg [27:0] faces [0:511];
    reg [27:0] face_q;
    (* ram_style="block", no_rw_check *) reg [23:0] projected [0:255];
    reg [7:0] vertex_address;
    reg [23:0] vertex_q;
    (* ram_style="block", no_rw_check *) reg [7:0] depth_buffer [0:32767];
    reg [7:0] depth_q;
    wire [14:0] pixel_address=({7'b0,py}<<7)+({7'b0,py}<<5)+{7'b0,px};
    wire inside_triangle=(!e0[19] && !e1[19] && !e2[19]) ||
                         ((e0<=0) && (e1<=0) && (e2<=0));
    wire hit=(state==DEPTH && inside_triangle && depth_value<depth_q);
    assign busy=(state!=IDLE);
    assign write_enable=(state==CLEAR) || hit;
    assign write_address=(state==CLEAR)?clear_address:pixel_address;
    assign write_data=(state==CLEAR)?4'd0:shade;
    initial begin
        $readmemh("assets/vertices.hex",vertices);
        $readmemh("assets/rotations.hex",rotations);
        $readmemh("assets/faces.hex",faces);
    end
    wire core_busy,core_done;
    wire read_result=(state==READ_X || state==READ_Y || state==READ_Z);
    wire [1:0] result_col=(state==READ_X)?2'd0:(state==READ_Y)?2'd1:2'd2;
    wire signed [31:0] result;
    wire [9:0] operand_address={base_vertex,2'b00}+{6'b0,load_index};
    wire signed [7:0] operand=(state==LOAD_B)?rotations[{angle,load_index}]:vertices[operand_address];
    tpu_core_wrapper #(.N(4),.DW(8),.CW(32)) tpu(
        .clk(clk),.rst(reset),.start(state==LAUNCH),.continue_accum(1'b0),
        .busy(core_busy),.done(core_done),
        .load_en(state==LOAD_A || state==LOAD_B),.load_sel(state==LOAD_B),
        .load_row(load_index[3:2]),.load_col(load_index[1:0]),.load_data(operand),
        .c_rd_en(read_result),.c_rd_row(result_row),.c_rd_col(result_col),.c_rd_data(result)
    );
    function automatic [7:0] min3(input [7:0] a,b,c);
        min3=(a<b)?((a<c)?a:c):((b<c)?b:c);
    endfunction
    function automatic [7:0] max3(input [7:0] a,b,c);
        max3=(a>b)?((a>c)?a:c):((b>c)?b:c);
    endfunction
    function automatic signed [9:0] difference(input [7:0] a,b);
        difference=$signed({2'b0,a})-$signed({2'b0,b});
    endfunction
    function automatic signed [19:0] edge_at(input [7:0] ax,ay,bx,by,x,y);
        edge_at=difference(bx,ax)*difference(y,ay)-difference(by,ay)*difference(x,ax);
    endfunction
    // Synchronous memories, including the render-side depth read. PIXEL gives
    // it one clock before DEPTH decides whether to commit the color and Z.
    always @(posedge clk) begin
        face_q<=faces[face_index];
        vertex_q<=projected[vertex_address];
        if(state==READ_Z) projected[base_vertex+{6'b0,result_row}]<=
            {8'(32'sd128+(result>>>7)),sy,sx};
        depth_q<=depth_buffer[pixel_address];
        if(state==CLEAR) depth_buffer[clear_address]<=255;
        else if(hit) depth_buffer[pixel_address]<=depth_value;
    end
    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE;done<=0;angle<=0;base_vertex<=0;load_index<=0;result_row<=0;
            clear_address<=0;face_index<=0;vertex_address<=0;sx<=0;sy<=0;
            vx0<=0;vy0<=0;vz0<=0;vx1<=0;vy1<=0;vz1<=0;vx2<=0;vy2<=0;vz2<=0;
            xmin<=0;xmax<=0;ymin<=0;ymax<=0;px<=0;py<=0;depth_value<=0;shade<=0;
            e0<=0;e1<=0;e2<=0;row0<=0;row1<=0;row2<=0;
            dx0<=0;dy0<=0;dx1<=0;dy1<=0;dx2<=0;dy2<=0;
        end else begin
            done<=0;
            case(state)
                IDLE: if(start) begin angle<=phase;clear_address<=0;state<=CLEAR;end
                CLEAR: if(clear_address==23039) begin load_index<=0;state<=LOAD_B;end
                       else clear_address<=clear_address+1'b1;
                LOAD_B: if(load_index==15) begin load_index<=0;base_vertex<=0;state<=LOAD_A;end
                        else load_index<=load_index+1'b1;
                LOAD_A: if(load_index==15) begin load_index<=0;state<=LAUNCH;end
                        else load_index<=load_index+1'b1;
                LAUNCH: state<=WAIT_TPU;
                WAIT_TPU: if(core_done) begin result_row<=0;state<=READ_X;end
                READ_X: begin sx<=8'(32'sd80+(result>>>8));state<=READ_Y;end
                READ_Y: begin sy<=8'(32'sd78-(result>>>8));state<=READ_Z;end
                READ_Z: if(result_row==3) begin
                    if(base_vertex==200) begin face_index<=0;state<=FACE;end
                    else begin base_vertex<=base_vertex+4;state<=LOAD_A;end
                end else begin result_row<=result_row+1'b1;state<=READ_X;end
                FACE: state<=FACE_WAIT;
                FACE_WAIT: begin vertex_address<=face_q[7:0];shade<=face_q[27:24];state<=V0_WAIT;end
                V0_WAIT: state<=V0;
                V0: begin {vz0,vy0,vx0}<=vertex_q;vertex_address<=face_q[15:8];state<=V1_WAIT;end
                V1_WAIT: state<=V1;
                V1: begin {vz1,vy1,vx1}<=vertex_q;vertex_address<=face_q[23:16];state<=V2_WAIT;end
                V2_WAIT: state<=V2;
                V2: begin {vz2,vy2,vx2}<=vertex_q;state<=BOUNDS;end
                BOUNDS: begin
                    xmin<=min3(vx0,vx1,vx2);xmax<=max3(vx0,vx1,vx2);
                    ymin<=min3(vy0,vy1,vy2);ymax<=max3(vy0,vy1,vy2);
                    depth_value<=8'(({2'b0,vz0}+{2'b0,vz1}+{2'b0,vz2})/10'd3);
                    dx0<=difference(vx1,vx0);dy0<=difference(vy1,vy0);
                    dx1<=difference(vx2,vx1);dy1<=difference(vy2,vy1);
                    dx2<=difference(vx0,vx2);dy2<=difference(vy0,vy2);
                    if(edge_at(vx0,vy0,vx1,vy1,vx2,vy2)==0) state<=NEXT_FACE;
                    else state<=EDGES;
                end
                EDGES: begin
                    px<=xmin;py<=ymin;
                    e0<=edge_at(vx0,vy0,vx1,vy1,xmin,ymin);row0<=edge_at(vx0,vy0,vx1,vy1,xmin,ymin);
                    e1<=edge_at(vx1,vy1,vx2,vy2,xmin,ymin);row1<=edge_at(vx1,vy1,vx2,vy2,xmin,ymin);
                    e2<=edge_at(vx2,vy2,vx0,vy0,xmin,ymin);row2<=edge_at(vx2,vy2,vx0,vy0,xmin,ymin);
                    state<=PIXEL;
                end
                PIXEL: state<=DEPTH;
                DEPTH: state<=ADVANCE;
                ADVANCE: if(px==xmax) begin
                    if(py==ymax) state<=NEXT_FACE;
                    else begin
                        px<=xmin;py<=py+1'b1;
                        row0<=row0+{{10{dx0[9]}},dx0};e0<=row0+{{10{dx0[9]}},dx0};
                        row1<=row1+{{10{dx1[9]}},dx1};e1<=row1+{{10{dx1[9]}},dx1};
                        row2<=row2+{{10{dx2[9]}},dx2};e2<=row2+{{10{dx2[9]}},dx2};
                        state<=PIXEL;
                    end
                end else begin
                    px<=px+1'b1;e0<=e0-{{10{dy0[9]}},dy0};
                    e1<=e1-{{10{dy1[9]}},dy1};e2<=e2-{{10{dy2[9]}},dy2};state<=PIXEL;
                end
                NEXT_FACE: if(face_index==406) begin done<=1;state<=IDLE;end
                           else begin face_index<=face_index+1'b1;state<=FACE;end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
