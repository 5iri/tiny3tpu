`timescale 1ns/1ps
module tb_renderer;
    reg clk=0;always #5 clk=~clk;
    reg reset=1,start=0;reg [7:0] phase=0;
    wire busy,done,we;wire [14:0] addr;wire [3:0] pixel;
    banana_renderer dut(clk,reset,start,phase,busy,done,we,addr,pixel);
    reg [31:0] expected_results [0:9791];
    reg [3:0] expected_pixels [0:368639];
    reg [3:0] frame [0:23039];
    integer frame_id=0,results=0,launches=0,clears=0,cycles=0,fd;
    bit checking=0;
    always @(posedge clk) if(!reset && checking)begin
        if(we)begin
            if(addr>=23040)$fatal(1,"Framebuffer out of bounds: %0d",addr);
            frame[addr]=pixel;
            if(dut.state==1)begin
                if(int'(addr)!=clears)$fatal(1,"clear address %0d expected %0d",addr,clears);
                clears=clears+1;
            end
        end
        if(dut.state==4) launches=launches+1;
        if(dut.read_result)begin
            if(dut.result!==expected_results[frame_id*612+results])
                $fatal(1,"TPU mismatch phase=%0d coordinate=%0d actual=%0d expected=%0d",
                    frame_id*16,results,dut.result,$signed(expected_results[frame_id*612+results]));
            results=results+1;
        end
    end
    initial begin
        $readmemh("build/expected-results.hex",expected_results);
        $readmemh("build/expected-pixels.hex",expected_pixels);
        repeat(4)@(negedge clk);reset=0;
        // Reset while work is in flight; the next START must clear partial work.
        start=1;phase=99;@(negedge clk);start=0;
        repeat(23100)@(negedge clk);reset=1;
        repeat(4)@(negedge clk);reset=0;
        for(frame_id=0;frame_id<16;frame_id=frame_id+1)begin
            checking=1;results=0;launches=0;clears=0;cycles=0;
            phase=8'(frame_id*16);start=1;
            @(negedge clk);start=0;
            while(!done)begin
                // Changes and extra START while busy must not alter this job.
                phase=8'(frame_id*16+7);start=(cycles==100);
                @(negedge clk);cycles=cycles+1;
                if(cycles>1000000)$fatal(1,"Render timeout");
            end
            start=0;
            if(results!=612 || launches!=51 || clears!=23040)
                $fatal(1,"Missing work: results=%0d launches=%0d clear=%0d",results,launches,clears);
            fd=$fopen($sformatf("build/frame-%03d.ppm",frame_id*16),"w");
            $fwrite(fd,"P3\n160 144\n255\n");
            for(integer i=0;i<23040;i=i+1)begin
                if(frame[i]!==expected_pixels[frame_id*23040+i])
                    $fatal(1,"Pixel mismatch phase=%0d address=%0d actual=%0d expected=%0d",frame_id*16,i,frame[i],expected_pixels[frame_id*23040+i]);
                if(frame[i]==0)$fwrite(fd,"8 12 28\n");
                else $fwrite(fd,"%0d %0d 8\n",120+int'(frame[i])*8,32+int'(frame[i])*12);
            end
            $fclose(fd);
            $display("FRAME phase=%0d cycles=%0d: 612 exact TPU coordinates, 23040 exact pixels",frame_id*16,cycles);
            checking=0;@(negedge clk);
        end
        $display("RENDERER PASS: 9792 coordinates, 368640 pixels, 816 actual tiny3tpu GEMMs, reset and busy START");
        $finish;
    end
endmodule
