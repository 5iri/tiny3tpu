`timescale 1ns/1ps
module tb_mujoco_cpu #(parameter BOOT_HEX="", RENDER_PC=0, MAX_CYCLES=1000000000, VIDEO_720P=0, WIDTH=320, HEIGHT=240, BOOT_WORDS=262144);
    localparam WORDS=WIDTH*HEIGHT/2, PERIOD=VIDEO_720P ? 1650*750 : 800*525;
    reg clk=0;always #5 clk=~clk;
    reg reset=1;
    wire [15:0] hdmi_d;
    wire de,hsync,vsync,frame_tick,valid,bank,pending,fault,exit_valid,report_valid;
    wire [31:0] frames,tag,exit_code,report_data;
    kc705_hdmi_pixel_system #(.BOOT_HEX(BOOT_HEX),.BOOT_WORDS(BOOT_WORDS),
        .FRAME_WIDTH(WIDTH),.FRAME_HEIGHT(HEIGHT),.VIDEO_720P(VIDEO_720P)) dut(
        .clk(clk),.reset(reset),.enable(1'b1),.test_pattern(1'b0),.hdmi_d(hdmi_d),
        .de(de),.hsync(hsync),.vsync(vsync),.frame_tick(frame_tick),.display_valid(valid),
        .display_bank(bank),.pending(pending),.frames(frames),.display_tag(tag),
        .fault(fault),.exit_valid(exit_valid),.report_valid(report_valid),.exit_code(exit_code),.report_data(report_data));
    integer cycle=0,core0=0,core1=0,writes=0,submits=0,fd,pfd,capture_left=0,captures=0,render_calls=0;
    reg tick=0,oldbank=0;reg [31:0] lastpc=0;
    string out_dir;
    always @(posedge clk)if(!reset)begin
        cycle=cycle+1;tick=frame_tick;
        if(fault || exit_valid)$fatal(1,"CPU fault or exit: %0d hex=%h pc=%h cycle=%0d",exit_code,exit_code,dut.soc.pc_debug,cycle);
        if(dut.soc.pc_debug==RENDER_PC && lastpc!=RENDER_PC)begin
            render_calls=render_calls+1;$display("MJR_RENDER call=%0d cycle=%0d",render_calls,cycle);$fflush();
        end
        lastpc=dut.soc.pc_debug;
        if(dut.soc.direct_tpu.accelerator.accelerator.u_top.core_start[0])core0=core0+1;
        if(dut.soc.direct_tpu.accelerator.accelerator.u_top.core_start[1])core1=core1+1;
        if(dut.display.pixel_write)begin
            if(writes%WORDS==0)pfd=$fopen($sformatf("%s/upload-%0d.rgb565",out_dir,submits),"wb");
            $fwrite(pfd,"%c%c%c%c",dut.display.req_wdata[7:0],dut.display.req_wdata[15:8],dut.display.req_wdata[23:16],dut.display.req_wdata[31:24]);
            writes=writes+1;
            if(writes%WORDS==0)$fclose(pfd);
        end
        if(report_valid)begin
            if(report_data!=32'(submits) || writes!=(submits+1)*WORDS)$fatal(1,"Missing CPU framebuffer upload");
            submits=submits+1;
        end
        if(cycle%10000000==0)begin $display("PROGRESS cycle=%0d pc=%h",cycle,dut.soc.pc_debug);$fflush();end
        if(cycle>MAX_CYCLES)$fatal(1,"Timeout");
    end
    initial begin
        if(!$value$plusargs("OUT_DIR=%s",out_dir))$fatal(1,"OUT_DIR required");
        fd=$fopen({out_dir,"/hdmi-stream.bin"},"wb");
        repeat(10)@(negedge clk);reset=0;
        while(captures<3 || capture_left>0)begin
            @(negedge clk);
            if(oldbank!=bank)begin
                if(!tick || de)$fatal(1,"Unsafe publication");
                if(capture_left>0)$fatal(1,"Capture overlap");
                $display("PUBLISH tag=%0d cycle=%0d",tag,cycle);$fflush();
                capture_left=2*PERIOD;captures=captures+1;
            end
            oldbank=bank;
            // Save exactly two whole video periods per publication. This bounds
            // trace size without changing CPU/TPU/display timing or skipping checks.
            if(capture_left>0)begin
                $fwrite(fd,"%c%c%c%c",hdmi_d[7:0],hdmi_d[15:8],{3'd0,bank,valid,vsync,hsync,de},tag[7:0]);
                capture_left=capture_left-1;
            end
        end
        $fclose(fd);
        if(core0!=16 || core1!=16 || submits!=3 || render_calls!=3)$fatal(1,"Incomplete execution");
        $display("MUJOCO_CPU_PASS cycles=%0d core0=%0d core1=%0d writes=%0d submits=%0d renderer=%0d",cycle,core0,core1,writes,submits,render_calls);
        $finish;
    end
endmodule
