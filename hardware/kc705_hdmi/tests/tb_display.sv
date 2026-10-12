`timescale 1ns/1ps
module tb_display;
    reg clk=0;
    always #5 clk=~clk;
    reg reset=1,enable=0,test_pattern=0;
    wire [15:0] hdmi_d,frames;
    wire de,hsync,vsync,frame_tick,render_busy,display_valid,display_bank;
    wire [31:0] render_cycles;
    wire [7:0] display_phase;
    kc705_hdmi_display dut(
        .clk(clk),.reset(reset),.enable(enable),.held(8'd0),.pressed(8'd0),
        .command_start(1'b0),.command_phase(8'd0),.command_ready(),
        .vertex_write(1'b0),.vertex_index(12'd0),.vertex_data(28'd0),
        .test_pattern(test_pattern),.hdmi_d(hdmi_d),.de(de),.hsync(hsync),
        .vsync(vsync),.frame_tick(frame_tick),.render_busy(render_busy),
        .display_valid(display_valid),.display_bank(display_bank),
        .render_cycles(render_cycles),.frames(frames),.display_phase(display_phase));

    reg [31:0] expected_results[0:9791];
    reg [3:0] expected_pixels[0:4915199];
    reg [3:0] working_frame[0:307199];
    reg checking=0,render_inflight=0,completed=0,pre_frame_tick=0;
    reg last_bank=0,last_valid=0;
    reg [7:0] last_phase=0;
    reg [31:0] last_cycles=0;
    integer job_phase=0,results=0,launches=0,clears=0;
    integer completed_phase=-1,completed_jobs=0,total_results=0,total_pixels=0,total_gemms=0;
    integer checked_results=0,checked_launches=0;
    integer concurrent_writes=0,publications=0,job_cycles=0;
    integer sample=0,capture_fd,state_fd;
    string out_dir;

    function automatic [3:0] published_pixel(input reg bank,input integer address);
        reg [7:0] pair_data;
        case(address/65536)
            0:pair_data=bank ? {dut.frame_memory.bank1.chunks[0].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank1.chunks[0].lanes[0].memory[(address/2)%32768]} : {dut.frame_memory.bank0.chunks[0].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank0.chunks[0].lanes[0].memory[(address/2)%32768]};
            1:pair_data=bank ? {dut.frame_memory.bank1.chunks[1].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank1.chunks[1].lanes[0].memory[(address/2)%32768]} : {dut.frame_memory.bank0.chunks[1].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank0.chunks[1].lanes[0].memory[(address/2)%32768]};
            2:pair_data=bank ? {dut.frame_memory.bank1.chunks[2].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank1.chunks[2].lanes[0].memory[(address/2)%32768]} : {dut.frame_memory.bank0.chunks[2].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank0.chunks[2].lanes[0].memory[(address/2)%32768]};
            3:pair_data=bank ? {dut.frame_memory.bank1.chunks[3].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank1.chunks[3].lanes[0].memory[(address/2)%32768]} : {dut.frame_memory.bank0.chunks[3].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank0.chunks[3].lanes[0].memory[(address/2)%32768]};
            4:pair_data=bank ? {dut.frame_memory.bank1.chunks[4].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank1.chunks[4].lanes[0].memory[(address/2)%32768]} : {dut.frame_memory.bank0.chunks[4].lanes[1].memory[(address/2)%32768], dut.frame_memory.bank0.chunks[4].lanes[0].memory[(address/2)%32768]};
            default:pair_data=0;
        endcase
        published_pixel=address[0] ? pair_data[7:4] : pair_data[3:0];
    endfunction

    // Observe the real accelerator readback and renderer write bus before each
    // rising edge. The oracle uses scalar products and direct edge equations.
    always @(posedge clk) begin
        pre_frame_tick=frame_tick;
        if(reset)begin
            render_inflight=0;completed=0;
        end else if(checking)begin
            if(dut.renderer.start && !dut.renderer.busy)begin
                if(render_inflight)$fatal(1,"Started over unfinished render");
                job_phase=int'(dut.renderer.phase);
                if(job_phase>=16)$fatal(1,"Reference phase range exceeded");
                render_inflight=1;results=0;launches=0;clears=0;job_cycles=0;
            end
            if(render_inflight)job_cycles=job_cycles+1;
            if(dut.renderer.write_enable)begin
                if(!render_inflight)$fatal(1,"Write outside a render");
                if(dut.renderer.write_address>=153600)$fatal(1,"Render address out of range");
                for(integer lane=0;lane<2;lane=lane+1)
                    if(dut.renderer.write_mask[lane])
                        working_frame[int'(dut.renderer.write_address)*2+lane]=dut.renderer.write_data[lane*4+:4];
                if(dut.renderer.state==1)begin
                    if(int'(dut.renderer.write_address)!=clears)$fatal(1,"Clear order mismatch");
                    clears=clears+1;
                end
                if(display_valid)begin
                    concurrent_writes=concurrent_writes+1;
                    if(dut.frame_memory.write_address[18]==display_bank)
                        $fatal(1,"Renderer wrote the visible bank");
                end
            end
            if(dut.renderer.state==4)begin launches=launches+1;checked_launches=checked_launches+1;end
            if(dut.renderer.read_result)begin
                if(results>=612)$fatal(1,"Too many TPU coordinates");
                if(dut.renderer.result!==expected_results[job_phase*612+results])
                    $fatal(1,"TPU mismatch phase=%0d coordinate=%0d actual=%0d expected=%0d",
                        job_phase,results,dut.renderer.result,$signed(expected_results[job_phase*612+results]));
                results=results+1;checked_results=checked_results+1;
            end
            if(dut.renderer.done)begin
                if(!render_inflight || results!=612 || launches!=51 || clears!=153600)
                    $fatal(1,"Incomplete render phase=%0d results=%0d launches=%0d clears=%0d",job_phase,results,launches,clears);
                for(integer i=0;i<307200;i=i+1)begin
                    if(working_frame[i]!==expected_pixels[job_phase*307200+i])
                        $fatal(1,"Raster mismatch phase=%0d address=%0d",job_phase,i);
                end
                if(job_cycles>=420000)$fatal(1,"Render missed 60 Hz budget");
                total_results=total_results+results;total_pixels=total_pixels+307200;total_gemms=total_gemms+launches;
                completed=1;completed_phase=job_phase;completed_jobs=completed_jobs+1;
                render_inflight=0;
                $display("RENDER phase=%0d cycles=%0d coordinates=%0d pixels=307200 gemms=%0d",job_phase,job_cycles,results,launches);
            end
        end
    end

    initial begin
        if(!$value$plusargs("OUT_DIR=%s",out_dir))$fatal(1,"OUT_DIR required");
        $readmemh({out_dir,"/expected-results.hex"},expected_results);
        $readmemh({out_dir,"/expected-pixels.hex"},expected_pixels);
        repeat(4)@(negedge clk);reset=0;
        // Reset actual TPU/render work after its framebuffer clear has started.
        repeat(153680)@(negedge clk);reset=1;
        repeat(4)@(negedge clk);
        reset=0;checking=1;
        capture_fd=$fopen({out_dir,"/hdmi-stream.bin"},"wb");
        state_fd=$fopen({out_dir,"/states.txt"},"w");
        if(capture_fd==0 || state_fd==0)$fatal(1,"Cannot open captures");
        for(sample=0;sample<420000*10;sample=sample+1)begin
            @(negedge clk);
            // Deliberate mid-frame changes: output mode/enable must wait for
            // vertical blank, including return from a disabled display.
            if(sample==100000)enable=1;
            if(sample==420000*2+100000)test_pattern=1;
            if(sample==420000*4+100000)test_pattern=0;
            if(sample==420000*6+100000)enable=0;
            if(sample==420000*7+100000)enable=1;
            if(display_bank!=last_bank)begin
                if(!pre_frame_tick || de || !completed || int'(display_phase)!=completed_phase)
                    $fatal(1,"Unsafe publication sample=%0d tick=%0d DE=%0d phase=%0d complete=%0d",sample,pre_frame_tick,de,display_phase,completed_phase);
                for(integer i=0;i<307200;i=i+1)begin
                    if(published_pixel(display_bank,i)!==expected_pixels[int'(display_phase)*307200+i])
                        $fatal(1,"Published memory mismatch phase=%0d address=%0d",display_phase,i);
                end
                publications=publications+1;completed=0;
            end
            if(de && (display_bank!=last_bank || display_phase!=last_phase || display_valid!=last_valid))
                $fatal(1,"Visible frame state changed during active video");
            if(sample==0 || display_bank!=last_bank || display_valid!=last_valid || display_phase!=last_phase || render_cycles!=last_cycles)
                $fwrite(state_fd,"%0d %0d %0d %0d %0d %0d\n",sample,display_valid,display_bank,display_phase,render_cycles,frames);
            last_bank=display_bank;last_phase=display_phase;last_valid=display_valid;last_cycles=render_cycles;
            $fwrite(capture_fd,"%c%c%c",hdmi_d[7:0],hdmi_d[15:8],
                {frame_tick,test_pattern,enable,display_bank,display_valid,vsync,hsync,de});
        end
        checking=0;$fclose(capture_fd);$fclose(state_fd);
        if(completed_jobs<9 || publications<9 || concurrent_writes<307200)
            $fatal(1,"Insufficient completed/concurrent work");
        $display("HDMI_RTL_PASS coordinates=%0d pixels=%0d gemms=%0d renders=%0d publications=%0d concurrent_writes=%0d samples=%0d",
            total_results,total_pixels,total_gemms,completed_jobs,publications,concurrent_writes,sample);
        $display("HDMI_INCLUDING_INFLIGHT coordinates=%0d launches=%0d",checked_results,checked_launches);
        $finish;
    end
    initial begin #50000000;$fatal(1,"Bounded HDMI test timeout");end
endmodule
