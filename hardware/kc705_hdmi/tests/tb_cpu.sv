`timescale 1ns/1ps
`include "mesh_config.vh"
module tb_cpu #(parameter BOOT_HEX="", parameter PHASES=9);
    localparam FIXTURE_PHASES=PHASES>12 ? 256 : 12;
    reg clk=0;
    always #5 clk=~clk;
    reg reset=1;
    wire [15:0] hdmi_d,frames;
    wire de,hsync,vsync,frame_tick,render_busy,display_valid,display_bank;
    wire fault,exit_valid,report_valid,cpu_error;
    wire [31:0] render_cycles,exit_code,report_data;
    wire [7:0] display_phase;
    kc705_hdmi_cpu_system #(.BOOT_HEX(BOOT_HEX)) dut(
        .clk(clk),.reset(reset),.enable(1'b1),.test_pattern(1'b0),.held(8'd0),.pressed(8'd0),
        .hdmi_d(hdmi_d),.frames(frames),.de(de),.hsync(hsync),.vsync(vsync),.frame_tick(frame_tick),
        .render_busy(render_busy),.display_valid(display_valid),.display_bank(display_bank),
        .render_cycles(render_cycles),.display_phase(display_phase),
        .fault(fault),.exit_valid(exit_valid),.exit_code(exit_code),
        .report_valid(report_valid),.report_data(report_data),.cpu_error(cpu_error));
    reg [27:0] expected_vertices[0:FIXTURE_PHASES*`HDMI_VERTICES-1];
    reg [31:0] expected_raw[0:FIXTURE_PHASES*(`HDMI_VERTICES*3)-1];
    reg [5:0] expected_pixels[0:3686399];
    reg [27:0] uploaded[0:`HDMI_VERTICES-1];
    reg [5:0] working_frame[0:307199];
    integer cycle=0,upload_count=0,submissions=0,renders=0,clears=0,render_start_cycle=0;
    integer core0=0,core1=0,previous_core0=0,previous_core1=0,job_phase=0;
    integer publications=0,capture_fd,end_cycle=-1,capture_end_cycle=-1;
    integer raw_checks=0,raw_row,raw_col;
    reg last_bank=0,pre_frame_tick=0;
    string out_dir;
    always @(posedge clk)if(!reset)begin
        cycle=cycle+1;pre_frame_tick=frame_tick;
        if(fault || exit_valid || cpu_error)$fatal(1,"CPU fault/exit cycle=%0d code=%0d",cycle,exit_code);
        if(dut.soc.direct_tpu.accelerator.accelerator.u_top.core_start[0])core0=core0+1;
        if(dut.soc.direct_tpu.accelerator.accelerator.u_top.core_start[1])core1=core1+1;
        if(dut.soc.direct_tpu.accelerator.resp_valid && dut.soc.direct_tpu.accelerator.resp_ready &&
           !dut.soc.direct_tpu.accelerator.writing && dut.soc.direct_tpu.accelerator.address[9])begin
            raw_row=(core0-previous_core0-1)*32+int'(dut.soc.direct_tpu.accelerator.address[8:4]);
            raw_col=int'(dut.soc.direct_tpu.accelerator.address[3:2]);
            if(raw_row>=`HDMI_VERTICES || raw_row<0 || raw_col>=3)
                $fatal(1,"Unexpected result read");
            if(dut.soc.direct_tpu.accelerator.resp_rdata!==expected_raw[(submissions%FIXTURE_PHASES)*(`HDMI_VERTICES*3)+raw_row*3+raw_col])
                $fatal(1,"Raw TPU/JAX mismatch phase=%0d row=%0d col=%0d",submissions,raw_row,raw_col);
            raw_checks=raw_checks+1;
        end
        if(dut.vertex_write)begin
            if(int'(dut.vertex_index)!=upload_count)$fatal(1,"Vertex upload order");
            uploaded[upload_count]=dut.vertex_data;upload_count=upload_count+1;
        end
        if(dut.command_start)begin
            if(upload_count!=`HDMI_VERTICES || int'(dut.command_phase)>=FIXTURE_PHASES)$fatal(1,"Incomplete submit");
            if(core0-previous_core0!=((`HDMI_VERTICES+31)/32) || core1-previous_core1!=((`HDMI_VERTICES+31)/32))
                $fatal(1,"Both TPU cores must execute the configured batches: %0d/%0d",core0-previous_core0,core1-previous_core1);
            previous_core0=core0;previous_core1=core1;
            for(integer i=0;i<`HDMI_VERTICES;i=i+1)
                if(uploaded[i]!==expected_vertices[int'(dut.command_phase)*`HDMI_VERTICES+i])
                    $fatal(1,"JAX projected vertex mismatch phase=%0d vertex=%0d",dut.command_phase,i);
            job_phase=int'(dut.command_phase);upload_count=0;submissions=submissions+1;clears=0;
            $display("SUBMIT phase=%0d cycle=%0d core0_batches=%0d core1_batches=%0d",job_phase,cycle,core0,core1);
        end
        if(dut.video.renderer.start)render_start_cycle=cycle;
        if(dut.video.renderer.write_enable)begin
            if(dut.video.renderer.write_address>=153600)$fatal(1,"Raster out of bounds");
            if(dut.video.frame_memory.write_address[18]==display_bank)$fatal(1,"Write visible bank");
            if(dut.video.renderer.state==1)begin
                if(int'(dut.video.renderer.write_address)!=clears)$fatal(1,"Clear order");
                clears=clears+1;
            end
            for(integer lane=0;lane<2;lane=lane+1)
                if(dut.video.renderer.write_mask[lane])
                    working_frame[int'(dut.video.renderer.write_address)*2+lane]=dut.video.renderer.write_data[lane*6+:6];
        end
        if(dut.video.renderer.done)begin
            if(clears!=153600)$fatal(1,"Incomplete clear");
            if(job_phase<12)for(integer i=0;i<307200;i=i+1)
                if(working_frame[i]!==expected_pixels[job_phase*307200+i])
                    $fatal(1,"JAX raster mismatch phase=%0d address=%0d",job_phase,i);
            renders=renders+1;
            $display("RASTER phase=%0d cycles=%0d",job_phase,cycle-render_start_cycle);
        end
        if(report_valid && report_data[31:24]!=8'hba)$fatal(1,"Unexpected firmware report");
    end
    initial begin
        if(!$value$plusargs("OUT_DIR=%s",out_dir))$fatal(1,"OUT_DIR required");
        $readmemh({out_dir,"/expected-vertices.hex"},expected_vertices);
        $readmemh({out_dir,"/expected-raw.hex"},expected_raw);
        $readmemh({out_dir,"/expected-pixels.hex"},expected_pixels);
        capture_fd=$fopen({out_dir,"/hdmi-stream.bin"},"wb");
        repeat(10)@(negedge clk);reset=0;
        while(end_cycle<0 || cycle<end_cycle)begin
            @(negedge clk);
            if(display_bank!=last_bank)begin
                if(!pre_frame_tick || de || renders!=publications+1)$fatal(1,"Unsafe publication");
                publications=publications+1;
                $display("PUBLISH phase=%0d cycle=%0d",display_phase,cycle);
                if(publications==9)capture_end_cycle=cycle+40000;
                if(publications==PHASES)end_cycle=cycle+40000;
            end
            last_bank=display_bank;
            if(capture_end_cycle<0 || cycle<=capture_end_cycle)
            $fwrite(capture_fd,"%c%c%c%c",hdmi_d[7:0],hdmi_d[15:8],
                {3'd0,display_bank,display_valid,vsync,hsync,de},display_phase);
            if(cycle>(PHASES+3)*1200000)$fatal(1,"CPU/HDMI bounded cycle timeout");
        end
        $fclose(capture_fd);
        $display("CPU_HDMI_PASS submissions=%0d renders=%0d publications=%0d core0=%0d core1=%0d raw_checks=%0d",submissions,renders,publications,core0,core1,raw_checks);
        $finish;
    end
endmodule
