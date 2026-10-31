`default_nettype none
// Publish only a completed back buffer, only during vertical blank.
module scene(input wire clk,reset,frame_tick,render_done,
    input wire [7:0] held,pressed,
    output reg render_start,display_bank,display_valid,
    output reg [7:0] phase,display_phase,
    output reg paused,reverse,
    output reg [2:0] speed,
    output reg [31:0] last_cycles,
    output reg [15:0] frames);
    localparam BEGIN=0,RENDER=1,PUBLISH=2;
    reg [1:0] state;
    reg [31:0] cycles;
    reg home_pending;
    always @(posedge clk) begin
        if(reset) begin
            state<=BEGIN;render_start<=0;display_bank<=0;display_valid<=0;
            phase<=0;display_phase<=0;paused<=0;reverse<=0;speed<=1;
            cycles<=0;last_cycles<=0;frames<=0;home_pending<=0;
        end else begin
            render_start<=0;
            if(pressed[0]) paused<=!paused;
            if(pressed[1]) reverse<=!reverse;
            if(pressed[2] && speed<4) speed<=speed+1'b1;
            if(pressed[3] && speed>1) speed<=speed-1'b1;
            if(pressed[6] || pressed[7]) home_pending<=1;
            case(state)
                BEGIN: begin render_start<=1;cycles<=0;state<=RENDER;end
                RENDER: begin
                    // The first RENDER clock is the accepted START edge.
                    cycles<=cycles+1'b1;
                    if(render_done) begin last_cycles<=cycles;state<=PUBLISH;end
                end
                PUBLISH: if(frame_tick) begin
                    display_bank<=!display_bank;display_valid<=1;
                    display_phase<=phase;frames<=frames+1'b1;state<=BEGIN;
                    if(home_pending) begin phase<=0;home_pending<=0;end
                    else if(held[4] && !held[5]) phase<=phase-{5'b0,speed};
                    else if(held[5] && !held[4]) phase<=phase+{5'b0,speed};
                    else if(!paused && !(held[4] && held[5]))
                        phase<=reverse?phase-{5'b0,speed}:phase+{5'b0,speed};
                end
                default: state<=BEGIN;
            endcase
        end
    end
endmodule
`default_nettype wire
