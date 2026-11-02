`default_nettype none
`include "mesh_config.vh"
// Ordered request/response target at 0x40000000. Full-word writes only.
// Vertex writes must be sequential through the configured vertex count, while ready, before each submit.
module kc705_hdmi_mmio(
    input wire clk,reset,
    input wire req_valid,output wire req_ready,
    input wire req_write,input wire [31:0] req_addr,req_wdata,
    input wire [3:0] req_wstrb,
    output reg resp_valid,input wire resp_ready,
    output reg [31:0] resp_rdata,output reg resp_error,
    input wire command_ready,render_busy,display_valid,
    input wire [7:0] held,pressed,display_phase,
    input wire [31:0] render_cycles,input wire [15:0] frames,
    output reg command_start,vertex_write,
    output reg [7:0] command_phase,
    output reg [11:0] vertex_index,
    output reg [27:0] vertex_data
);
    localparam VERTICES=`HDMI_VERTICES;
    reg [12:0] upload_count;
    reg [7:0] sticky_pressed;
    assign req_ready=!resp_valid;
    always @(posedge clk)begin
        if(reset)begin
            resp_valid<=0;resp_rdata<=0;resp_error<=0;
            command_start<=0;command_phase<=0;vertex_write<=0;vertex_index<=0;vertex_data<=0;
            upload_count<=0;sticky_pressed<=0;
        end else begin
            command_start<=0;vertex_write<=0;sticky_pressed<=sticky_pressed|pressed;
            if(resp_valid && resp_ready)resp_valid<=0;
            if(req_valid && req_ready)begin
                resp_valid<=1;resp_error<=0;resp_rdata<=0;
                if(req_addr[31:17]!=15'h2000 || req_addr[1:0]!=0 || (req_write && req_wstrb!=15))
                    resp_error<=1;
                else if(req_write)begin
                    if(req_addr[16:0]==17'h008)begin
                        if(!command_ready || upload_count!=VERTICES || req_wdata[31:8]!=24'h800000)
                            resp_error<=1;
                        else begin command_start<=1;command_phase<=req_wdata[7:0];upload_count<=0;end
                    end else if(req_addr[16:0]==17'h014)
                        sticky_pressed<=(sticky_pressed&~req_wdata[7:0])|pressed;
                    else if(req_addr[16:14]==4 && req_addr[13:2]<VERTICES)begin
                        if(!command_ready || {1'b0,req_addr[13:2]}!=upload_count || req_wdata[31:28]!=0 ||
                           req_wdata[9:0]>=640 || req_wdata[19:10]>=480 || req_wdata[27:20]==255)
                            resp_error<=1;
                        else begin
                            vertex_write<=1;vertex_index<=upload_count[11:0];vertex_data<=req_wdata[27:0];
                            upload_count<=upload_count+1'b1;
                        end
                    end else resp_error<=1;
                end else case(req_addr[16:0])
                    17'h000:resp_rdata<=32'h48444d49;
                    17'h004:resp_rdata<={29'd0,display_valid,render_busy,command_ready};
                    17'h00c:resp_rdata<={19'd0,upload_count};
                    17'h010:resp_rdata<={24'd0,held};
                    17'h014:resp_rdata<={24'd0,sticky_pressed};
                    17'h018:resp_rdata<=render_cycles;
                    17'h01c:resp_rdata<={16'd0,frames};
                    17'h024:resp_rdata<=VERTICES;
                    17'h028:resp_rdata<=`HDMI_TRIANGLES;
                    17'h020:resp_rdata<={24'd0,display_phase};
                    default:resp_error<=1;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
