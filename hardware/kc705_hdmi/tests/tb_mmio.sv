`timescale 1ns/1ps
`include "mesh_config.vh"
module tb_mmio;
    reg clk=0;always #5 clk=~clk;
    reg reset=1,req_valid=0,req_write=0,resp_ready=0;
    reg [31:0] req_addr=0,req_wdata=0;
    reg [3:0] req_wstrb=15;
    wire req_ready,resp_valid,resp_error,command_start,vertex_write;
    wire [31:0] resp_rdata;
    wire [7:0] command_phase;
    wire [11:0] vertex_index;
    wire [27:0] vertex_data;
    reg command_ready=1,render_busy=0;
    reg [7:0] pressed=0;
    integer vertices=0,submits=0,transactions=0;
    reg [31:0] result;
    kc705_hdmi_mmio dut(.clk(clk),.reset(reset),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.req_wstrb(req_wstrb),
        .resp_valid(resp_valid),.resp_ready(resp_ready),.resp_rdata(resp_rdata),.resp_error(resp_error),
        .command_ready(command_ready),.render_busy(render_busy),.display_valid(1'b0),
        .held(8'h10),.pressed(pressed),.display_phase(8'd0),.render_cycles(32'd123),.frames(16'd7),
        .command_start(command_start),.command_phase(command_phase),
        .vertex_write(vertex_write),.vertex_index(vertex_index),.vertex_data(vertex_data));
    always @(posedge clk)if(!reset)begin
        if(vertex_write)begin
            if(int'(vertex_index)!=vertices)$fatal(1,"Repeated/out-of-order vertex side effect");
            vertices=vertices+1;
        end
        if(command_start)begin
            if(command_phase!=8'h5a)$fatal(1,"Phase payload");
            submits=submits+1;
        end
    end
    task access(input bit write,input [31:0] address,data,input [3:0] strobe,input bit error);
        reg [31:0] held_response;
        begin
            @(negedge clk);while(!req_ready)@(negedge clk);
            req_valid=1;req_write=write;req_addr=address;req_wdata=data;req_wstrb=strobe;
            @(negedge clk);req_valid=0;
            if(!resp_valid || resp_error!=error)$fatal(1,"Bad response addr=%h",address);
            held_response=resp_rdata;result=resp_rdata;
            repeat(3)begin
                @(negedge clk);
                if(!resp_valid || resp_rdata!==held_response || resp_error!=error || req_ready)
                    $fatal(1,"Response changed under backpressure");
            end
            resp_ready=1;@(negedge clk);resp_ready=0;
            if(resp_valid)$fatal(1,"Response not consumed");
            transactions=transactions+1;
        end
    endtask
    initial begin
        repeat(3)@(negedge clk);reset=0;
        access(0,32'h40000000,0,15,0);if(result!=32'h48444d49)$fatal(1,"ID");
        access(1,32'h40000008,32'h8000005a,15,1);
        access(1,32'h40010004,0,15,1);
        access(1,32'h40010000,0,3,1);
        access(1,32'h40010000,640,15,1);
        access(1,32'h40010000,480<<10,15,1);
        access(1,32'h40010000,255<<20,15,1);
        access(0,32'h40020000,0,15,1);
        access(0,32'h40000001,0,15,1);
        access(0,32'h40000024,0,15,0);if(result!=`HDMI_VERTICES)$fatal(1,"Mesh vertex count");
        access(0,32'h40000028,0,15,0);if(result!=`HDMI_TRIANGLES)$fatal(1,"Mesh triangle count");
        access(1,32'h40010000+4*`HDMI_VERTICES,0,15,1); // One past the final vertex.
        access(1,32'h40000400,0,15,1); // Retired 8-bit aperture.
        access(0,32'h40010024,0,15,1); // Do not alias control registers.
        command_ready=0;render_busy=1;
        access(1,32'h40010000,0,15,1);
        access(0,32'h40000004,0,15,0);if(result!=2)$fatal(1,"Busy status");
        command_ready=1;render_busy=0;
        for(integer i=0;i<`HDMI_VERTICES;i=i+1)
            access(1,32'h40010000+4*i,(100<<20)|(200<<10)|(i%640),15,0);
        access(0,32'h4000000c,0,15,0);if(result!=`HDMI_VERTICES)$fatal(1,"Upload count");
        access(1,32'h40000008,32'h0000005a,15,1);
        access(1,32'h40000008,32'h8000005a,15,0);
        access(1,32'h40000008,32'h8000005a,15,1);
        access(0,32'h4000000c,0,15,0);if(result!=0)$fatal(1,"Upload reset");
        @(negedge clk);pressed=5;@(negedge clk);pressed=0;
        access(0,32'h40000014,0,15,0);if(result!=5)$fatal(1,"Sticky input");
        access(1,32'h40000014,1,15,0);
        access(0,32'h40000014,0,15,0);if(result!=4)$fatal(1,"W1C");
        if(vertices!=`HDMI_VERTICES || submits!=1)$fatal(1,"Side effect count");
        $display("MMIO_PASS transactions=%0d vertices=%0d submits=%0d",transactions,vertices,submits);
        $finish;
    end
    initial begin #2000000;$fatal(1,"Timeout");end
endmodule
