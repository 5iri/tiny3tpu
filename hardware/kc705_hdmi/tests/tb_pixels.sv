`timescale 1ns/1ps
module tb_pixels #(parameter VIDEO_720P=0, WIDTH=160, HEIGHT=120);
    localparam WORDS=WIDTH*HEIGHT/2, PERIOD=VIDEO_720P ? 1650*750 : 800*525;
    reg clk=0;always #5 clk=~clk;
    reg reset=1,req_valid=0,req_write=0,resp_ready=0;
    reg [31:0] req_addr=0,req_wdata=0;
    reg [3:0] req_wstrb=15;
    wire req_ready,resp_valid,resp_error,de,hsync,vsync,frame_tick,bank,valid,pending;
    wire [31:0] resp_rdata,frames,tag;
    wire [15:0] hdmi_d;
    kc705_hdmi_pixels
`ifndef SYNTHESIZED
        #(.WIDTH(WIDTH),.HEIGHT(HEIGHT),.VIDEO_720P(VIDEO_720P))
`endif
        dut(.clk(clk),.reset(reset),.enable(1'b1),.test_pattern(1'b0),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.req_wstrb(req_wstrb),.resp_valid(resp_valid),.resp_ready(resp_ready),
        .resp_rdata(resp_rdata),.resp_error(resp_error),.hdmi_d(hdmi_d),.de(de),.hsync(hsync),.vsync(vsync),
        .frame_tick(frame_tick),.display_bank(bank),.display_valid(valid),.pending(pending),.frames(frames),.display_tag(tag));
    integer checks=0,fd,cycle=0;reg oldbank=0,tick=0;string out_dir;
    always @(posedge clk)begin
        tick=frame_tick;
        if(!reset && dut.pixel_write && pending)$fatal(1,"Write while pending");
    end
    always @(negedge clk)begin
        cycle=cycle+1;
        if(!reset && oldbank!=bank && (!tick || de))$fatal(1,"Unsafe publication");
        oldbank=bank;
        if(fd)$fwrite(fd,"%c%c%c%c",hdmi_d[7:0],hdmi_d[15:8],{3'd0,bank,valid,vsync,hsync,de},tag[7:0]);
        if(cycle>10*PERIOD)$fatal(1,"Timeout");
    end
    task automatic transaction(input bit wr,input [31:0] addr,data,input [3:0] strb,input bit error,input [31:0] wanted);
        reg [31:0] held_data;reg held_error;
        begin
            @(negedge clk);req_valid=1;req_write=wr;req_addr=addr;req_wdata=data;req_wstrb=strb;
            do @(posedge clk);while(!req_ready);
            @(negedge clk);req_valid=0;
            while(!resp_valid)@(negedge clk);
            if(resp_error!==error || (!wr && !error && resp_rdata!==wanted))
                $fatal(1,"MMIO addr=%h data=%h error=%b expected=%h/%b",addr,resp_rdata,resp_error,wanted,error);
            held_data=resp_rdata;held_error=resp_error;
            repeat(2)begin
                @(negedge clk);
                if(!resp_valid || req_ready || resp_rdata!==held_data || resp_error!==held_error)$fatal(1,"Backpressure");
            end
            resp_ready=1;@(negedge clk);resp_ready=0;checks=checks+1;
        end
    endtask
    function automatic [15:0] pixel(input integer index,phase);
        integer x,y;
        begin x=index%WIDTH;y=index/WIDTH;
            pixel={5'((x+phase*7)%32),6'((y+phase*11)%64),5'((x+y+phase*13)%32)};
        end
    endfunction
    initial begin
        if(!$value$plusargs("OUT_DIR=%s",out_dir))$fatal(1,"OUT_DIR required");
        fd=$fopen({out_dir,"/hdmi-stream.bin"},"wb");
        repeat(10)@(negedge clk);reset=0;
        transaction(0,'h40000000,0,15,0,'h50464231);
        transaction(0,'h40000010,0,15,0,WIDTH);
        transaction(0,'h40000014,0,15,0,HEIGHT);
        transaction(0,'h40000018,0,15,0,WORDS);
        transaction(0,'h40000024,0,15,0,565);
        transaction(0,'h40000028,0,15,0,VIDEO_720P ? 1280 : 640);
        transaction(0,'h4000002c,0,15,0,VIDEO_720P ? 720 : 480);
        transaction(0,'h40000030,0,15,0,VIDEO_720P ? 74250000 : 25200000);
        transaction(0,'h40000100,0,15,1,0);
        transaction(0,'h40100000,0,15,1,0);
        transaction(1,'h40000008,1,15,1,0); // incomplete frame
        transaction(1,'h40100004,0,15,1,0); // out of order
        transaction(1,'h40100000,0,3,1,0);  // partial write
        transaction(1,'h40100001,0,15,1,0);// unaligned
        transaction(1,32'h40100000+WORDS*4,0,15,1,0);// just beyond aperture
        transaction(0,'h4000000c,0,15,0,0);
        for(integer phase=0;phase<3;phase=phase+1)begin
            for(integer i=0;i<WORDS;i=i+1)
                transaction(1,32'h40100000+32'(i*4),{pixel(i*2+1,phase),pixel(i*2,phase)},15,0,0);
            transaction(0,'h4000000c,0,15,0,WORDS);
            transaction(1,'h40100000,0,15,1,0); // cannot overwrite completed upload
            transaction(1,'h40000008,32'(phase),15,0,0);
            transaction(1,'h40100000,0,15,1,0); // queued bank is immutable
            transaction(1,'h40000008,0,15,1,0);
            while(frames!=32'(phase+1))@(negedge clk);
            transaction(0,'h40000020,0,15,0,32'(phase));
            // Exercise CPU upload concurrently with active front-bank scanout.
            repeat(PERIOD/4)@(negedge clk);
        end
        repeat(2*PERIOD+10000)@(negedge clk);
        $fclose(fd);fd=0;
        // Reset invalidates display and incomplete uploads without clearing RAM.
        transaction(1,'h40100000,'hdeadbeef,15,0,0);
        @(negedge clk);reset=1;repeat(3)@(negedge clk);reset=0;
        transaction(0,'h40000004,0,15,0,1);
        transaction(0,'h4000000c,0,15,0,0);
        transaction(1,'h40000008,0,15,1,0);
        $display("PIXELS_PASS checks=%0d",checks);$finish;
    end
endmodule
