`default_nettype none
// Five independent 32K chunks, each containing two independently writable
// pixel lanes. Reads have one clock of latency, including chunk selection.
module kc705_hdmi_ram #(parameter WIDTH=4)(
    input wire clk,write_enable,
    input wire [1:0] write_mask,
    input wire [17:0] write_address,read_address,
    input wire [2*WIDTH-1:0] write_data,
    output wire [2*WIDTH-1:0] read_data
);
    wire [2*WIDTH-1:0] chunk_data[0:4];
    reg [2:0] read_chunk;
    always @(posedge clk) read_chunk<=read_address[17:15];
    for(genvar i=0;i<5;i=i+1) begin:chunks
        for(genvar lane=0;lane<2;lane=lane+1) begin:lanes
            (* ram_style="block", no_rw_check *) reg [WIDTH-1:0] memory[0:32767];
            reg [WIDTH-1:0] data;
            always @(posedge clk) begin
                if(write_enable && write_mask[lane] && write_address[17:15]==3'(i))
                    memory[write_address[14:0]]<=write_data[lane*WIDTH+:WIDTH];
                data<=memory[read_address[14:0]];
            end
            assign chunk_data[i][lane*WIDTH+:WIDTH]=data;
        end
    end
    assign read_data=read_chunk==0 ? chunk_data[0] :
                     read_chunk==1 ? chunk_data[1] :
                     read_chunk==2 ? chunk_data[2] :
                     read_chunk==3 ? chunk_data[3] :
                     read_chunk==4 ? chunk_data[4] : {2*WIDTH{1'b0}};
endmodule
`default_nettype wire
