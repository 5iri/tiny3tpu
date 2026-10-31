`timescale 1ns/1ps
module tb_pixel_cpu #(parameter BOOT_HEX="",PUBLICATIONS=5,CHECK_DUAL=1);
    reg clk=0;always #5 clk=~clk;
    reg reset=1;
    wire [15:0] hdmi_d;
    wire de,hsync,vsync,frame_tick,valid,bank,pending,fault,exit_valid,report_valid;
    wire [31:0] frames,tag,exit_code,report_data;
    kc705_hdmi_pixel_system #(.BOOT_HEX(BOOT_HEX)) dut(
        .clk(clk),.reset(reset),.enable(1'b1),.test_pattern(1'b0),.hdmi_d(hdmi_d),
        .de(de),.hsync(hsync),.vsync(vsync),.frame_tick(frame_tick),.display_valid(valid),
        .display_bank(bank),.pending(pending),.frames(frames),.display_tag(tag),
        .fault(fault),.exit_valid(exit_valid),.report_valid(report_valid),.exit_code(exit_code),.report_data(report_data));
    integer cycle=0,core0=0,core1=0,writes=0,submits=0,fd,finish_cycle=-1;
    reg tick=0,oldbank=0;string out_dir;
    always @(posedge clk)if(!reset)begin
        cycle=cycle+1;tick=frame_tick;
        if(fault || exit_valid)$fatal(1,"CPU fault or exit: %0d",exit_code);
        if(dut.soc.direct_tpu.accelerator.accelerator.u_top.core_start[0])core0=core0+1;
        if(dut.soc.direct_tpu.accelerator.accelerator.u_top.core_start[1])core1=core1+1;
        if(dut.display.pixel_write)writes=writes+1;
        if(report_valid)begin
            if(report_data!=32'(submits) || writes!=(submits+1)*9600 ||
               (CHECK_DUAL && (core0<submits+1 || core1<submits+1)))
                $fatal(1,"Missing CPU upload or dual TPU execution");
            submits=submits+1;
        end
        if(cycle>15000000)$fatal(1,"Timeout");
    end
    initial begin
        if(!$value$plusargs("OUT_DIR=%s",out_dir))$fatal(1,"OUT_DIR required");
        fd=$fopen({out_dir,"/hdmi-stream.bin"},"wb");
        repeat(10)@(negedge clk);reset=0;
        while(finish_cycle<0 || cycle<finish_cycle)begin
            @(negedge clk);
            if(oldbank!=bank)begin
                if(!tick || de)$fatal(1,"Unsafe publication");
                $display("PUBLISH tag=%0d cycle=%0d",tag,cycle);
            end
            oldbank=bank;
            $fwrite(fd,"%c%c%c%c",hdmi_d[7:0],hdmi_d[15:8],{3'd0,bank,valid,vsync,hsync,de},tag[7:0]);
            if(frames>=PUBLICATIONS && finish_cycle<0)finish_cycle=cycle+460000;
        end
        $fclose(fd);
        if(core0==0)$fatal(1,"No TPU execution");
        $display("PIXEL_CPU_PASS core0=%0d core1=%0d writes=%0d submits=%0d",core0,core1,writes,submits);
        $finish;
    end
endmodule
