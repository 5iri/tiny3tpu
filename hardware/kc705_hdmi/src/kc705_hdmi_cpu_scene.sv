`default_nettype none
// CPU owns geometry and phase. A submitted frame becomes writable again only
// after complete rasterization and publication during vertical blank.
module kc705_hdmi_cpu_scene(
    input wire clk,reset,frame_tick,render_done,command_start,
    input wire [7:0] command_phase,
    output wire command_ready,
    output reg render_start,display_bank,display_valid,
    output reg [7:0] phase,display_phase,
    output reg [31:0] last_cycles,
    output reg [15:0] frames
);
    localparam IDLE=0,RENDER=1,PUBLISH=2;
    reg [1:0] state;
    reg [31:0] cycles;
    reg refresh_phase;
    assign command_ready=state==IDLE;
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;render_start<=0;display_bank<=0;display_valid<=0;
            phase<=0;display_phase<=0;last_cycles<=0;frames<=0;cycles<=0;refresh_phase<=0;
        end else begin
            if(frame_tick)refresh_phase<=!refresh_phase;
            render_start<=0;
            case(state)
                IDLE:if(command_start)begin
                    phase<=command_phase;render_start<=1;cycles<=0;state<=RENDER;
                end
                RENDER:begin
                    cycles<=cycles+1'b1;
                    if(render_done)begin last_cycles<=cycles;state<=PUBLISH;end
                end
                PUBLISH:if(frame_tick && refresh_phase)begin
                    display_bank<=!display_bank;display_valid<=1;display_phase<=phase;
                    frames<=frames+1'b1;state<=IDLE;
                end
                default:state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
