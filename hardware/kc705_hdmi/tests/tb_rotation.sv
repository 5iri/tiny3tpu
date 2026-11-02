`timescale 1ns/1ps
`include "mesh_config.vh"
module tb_rotation #(parameter CPU_DRIVEN=0);
    localparam PIXEL_BITS=CPU_DRIVEN ? 6 : 4;
    localparam VERTICES=CPU_DRIVEN ? `HDMI_VERTICES : 204;
    reg clk=0;
    always #5 clk=~clk;
    reg reset=1,start=0;
    reg [7:0] phase=0;
    wire busy,done,write_enable;
    wire [17:0] write_address;
    wire [1:0] write_mask;
    wire [2*PIXEL_BITS-1:0] write_data;
    reg vertex_write=0;
    reg [11:0] vertex_index=0;
    reg [27:0] vertex_data=0;
    kc705_hdmi_renderer #(.CPU_DRIVEN(CPU_DRIVEN)) dut(.*);
    reg [31:0] expected_results[0:256*VERTICES*3-1];
    reg [PIXEL_BITS-1:0] expected_pixels[0:78643199];
    reg [PIXEL_BITS-1:0] frame[0:307199];
    integer results=0,clears=0,cycles=0;
    string out_dir;
    always @(posedge clk) if(!reset) begin
        if(start)begin results=0;clears=0;cycles=0;end
        if(start || busy)cycles=cycles+1;
        if(write_enable)begin
            if(write_address>=153600)$fatal(1,"Out of bounds phase=%0d",phase);
            for(integer lane=0;lane<2;lane=lane+1)
                if(write_mask[lane])frame[int'(write_address)*2+lane]=write_data[lane*PIXEL_BITS+:PIXEL_BITS];
            if(dut.state==1)begin
                if(int'(write_address)!=clears)$fatal(1,"Clear order");
                clears=clears+1;
            end
        end
        if(!CPU_DRIVEN && dut.read_result)begin
            if(results>=612 || dut.result!==expected_results[int'(phase)*612+results])
                $fatal(1,"TPU coordinate phase=%0d result=%0d",phase,results);
            results=results+1;
        end
    end
    initial begin
        if(!$value$plusargs("OUT_DIR=%s",out_dir))$fatal(1,"OUT_DIR required");
        $readmemh({out_dir,"/expected-results.hex"},expected_results);
        $readmemh({out_dir,"/expected-pixels.hex"},expected_pixels);
        repeat(4)@(negedge clk);reset=0;
        for(integer p=0;p<256;p=p+1)begin
            if(CPU_DRIVEN)begin
                for(integer v=0;v<VERTICES;v=v+1)begin
                    vertex_write=1;vertex_index=12'(v);
                    vertex_data={8'(128+($signed(expected_results[(p*VERTICES+v)*3+2])>>>7)),
                        10'(280-($signed(expected_results[(p*VERTICES+v)*3+1])>>>6)),
                        10'(320+($signed(expected_results[(p*VERTICES+v)*3])>>>6))};
                    @(negedge clk);
                end
                vertex_write=0;
            end
            phase=8'(p);start=1;@(negedge clk);start=0;
            while(!done)@(negedge clk);
            if((!CPU_DRIVEN && results!=612) || clears!=153600 || cycles>=(CPU_DRIVEN ? 840000 : 420000))
                $fatal(1,"Incomplete/late frame phase=%0d cycles=%0d",p,cycles);
            for(integer i=0;i<307200;i=i+1)
                if(frame[i]!==expected_pixels[p*307200+i])
                    $fatal(1,"Pixel mismatch phase=%0d address=%0d",p,i);
            $display("ROTATION phase=%0d cycles=%0d",p,cycles);
            @(negedge clk);
        end
        $display("ROTATION_PASS phases=256 coordinates=%0d pixels=78643200",256*VERTICES*3);
        $finish;
    end
    initial begin #2200000000;$fatal(1,"Rotation timeout");end
endmodule
