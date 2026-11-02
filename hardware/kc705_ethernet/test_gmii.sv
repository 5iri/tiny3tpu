`timescale 1ns/1ps
module test_gmii;
    reg sys_clk=0,eth_clk=0,rst=1;
    always #5 sys_clk=~sys_clk;
    always #4 eth_clk=~eth_clk;
    wire [7:0] gmii_data[0:1]; wire gmii_en[0:1],gmii_er[0:1];
    reg tx_valid=0;wire tx_ready;reg [31:0] tx_data=0;reg tx_last=0;
    reg [3:0] tx_last_be=0;reg [15:0] tx_length=0;
    wire rx_valid;reg rx_ready=0;wire [31:0] rx_data;wire rx_last;
    wire [3:0] rx_last_be,rx_error;wire [15:0] rx_length,rx_src,rx_dst;wire [31:0] rx_ip;
    wire [31:0] crc_errors[0:1],preamble_errors[0:1];
    reg corrupt=0,inject_error=0,expect_drop=0;reg [15:0] destination=9001;
    integer wire_count[0:1];integer wire_type[0:1];integer z;
    genvar g;
    generate for(g=0;g<2;g=g+1)begin: node
        wire unused_ready,unused_valid,unused_last;
        wire [31:0] unused_data,unused_ip;
        wire [3:0] unused_be,unused_error;
        wire [15:0] unused_src,unused_dst,unused_length;
        localparam [47:0] MAC=48'h020000007051+g;
        localparam [31:0] IP=32'hc0a80132+g;
        kc705_liteeth_udp core (
            .sys_clk(sys_clk),.sys_rst(rst),.eth_tx_clk(eth_clk),.gmii_rx_clk(eth_clk),
            .local_mac_address(MAC),.local_ip_address(IP),
            .gmii_rx_data(gmii_data[1-g] ^ ((g==1 && corrupt && wire_count[0]==55)?8'h01:8'h00)),
            .gmii_rx_dv(gmii_en[1-g]),.gmii_rx_er(gmii_er[1-g] | (g==1 && inject_error && wire_count[0]==55)),
            .gmii_gtx_clk(),.gmii_tx_data(gmii_data[g]),.gmii_tx_en(gmii_en[g]),.gmii_tx_er(gmii_er[g]),
            .tx_valid(g==0?tx_valid:1'b0),.tx_ready(unused_ready),
            .tx_data(tx_data),.tx_last(tx_last),.tx_last_be(tx_last_be),.tx_error(4'b0),
            .tx_src_port(16'd9001),.tx_dst_port(destination),.tx_ip_address(32'hc0a80133),.tx_length(tx_length),
            .rx_valid(unused_valid),.rx_ready(g==1?rx_ready:1'b1),
            .rx_data(unused_data),.rx_last(unused_last),
            .rx_last_be(unused_be),.rx_error(unused_error),
            .rx_src_port(unused_src),.rx_dst_port(unused_dst),
            .rx_ip_address(unused_ip),.rx_length(unused_length),
            .crc_errors(crc_errors[g]),.preamble_errors(preamble_errors[g]));
    end endgenerate
    assign tx_ready=node[0].unused_ready;
    assign rx_valid=node[1].unused_valid;
    assign rx_data=node[1].unused_data;
    assign rx_last=node[1].unused_last;
    assign rx_last_be=node[1].unused_be;
    assign rx_error=node[1].unused_error;
    assign rx_src=node[1].unused_src;
    assign rx_dst=node[1].unused_dst;
    assign rx_ip=node[1].unused_ip;
    assign rx_length=node[1].unused_length;
    initial begin wire_count[0]=0;wire_count[1]=0;wire_type[0]=0;wire_type[1]=0;end
    always @(posedge eth_clk) for(z=0;z<2;z=z+1)begin
        if(gmii_en[z])begin
            if(wire_count[z]==20)wire_type[z]=gmii_data[z]<<8;
            if(wire_count[z]==21)wire_type[z]=wire_type[z]|gmii_data[z];
            wire_count[z]=wire_count[z]+1;
        end else if(wire_count[z])begin
            if(wire_count[z]<72)$fatal(1,"Runt Ethernet frame: %0d bytes including preamble/FCS",wire_count[z]);
            $display("WIRE node=%0d bytes=%0d type=%h",z,wire_count[z],wire_type[z]);wire_count[z]=0;
        end
    end
    integer packets=0,received=0,wanted=0,cycle=0;
    integer i,lane,n,length;
    function [7:0] pattern;input integer offset,bytes;begin pattern=(offset*7+bytes)&255;end endfunction
    always @(negedge sys_clk) begin cycle=cycle+1;rx_ready=(cycle%7)!=0;end
    always @(posedge sys_clk) if(!rst && rx_valid && rx_ready) begin
        if(expect_drop)$fatal(1,"Invalid frame reached UDP application");
        if(rx_error || rx_length!=wanted || rx_src!=9001 || rx_dst!=9001 || rx_ip!=32'hc0a80132)
            $fatal(1,"metadata/error mismatch error=%h length=%d wanted=%d",rx_error,rx_length,wanted);
        n=rx_last ? ((wanted-1)%4+1) : 4;
        for(lane=0;lane<n;lane=lane+1)
            if(rx_data[8*lane+:8]!==pattern(received+lane,wanted))
                $fatal(1,"byte mismatch offset=%d data=%h",received+lane,rx_data);
        received=received+n;
        if(rx_last)begin
            if(received!=wanted || rx_last_be!=(1<<((wanted-1)%4)))$fatal(1,"length/last-be mismatch received=%d wanted=%d be=%h",received,wanted,rx_last_be);
            packets=packets+1;$display("PASS UDP payload=%0d bytes through ARP/IP/MAC/GMII",wanted);
        end
    end
    task send;
        input integer bytes;
        integer offset,j,previous;
        begin
            wanted=bytes;received=0;previous=packets;
            for(offset=0;offset<bytes;offset=offset+4)begin
                @(negedge sys_clk);tx_valid=1;tx_data=0;tx_length=bytes;
                tx_last=(offset+4>=bytes);tx_last_be=tx_last ? 1<<((bytes-1)%4):0;
                for(j=0;j<4;j=j+1) if(offset+j<bytes)tx_data[8*j+:8]=pattern(offset+j,bytes);
                @(posedge sys_clk);while(!tx_ready)@(posedge sys_clk);
            end
            @(negedge sys_clk);tx_valid=0;
            if(expect_drop)begin repeat(4000)@(posedge sys_clk);if(packets!=previous)$fatal(1,"bad frame accepted");end
            else begin wait(packets==previous+1);repeat(50)@(posedge sys_clk);end
        end
    endtask
    initial begin
        #100;rst=0;repeat(30)@(posedge sys_clk);
        send(1);send(2);send(3);send(4);send(17);send(1400);send(1472);
        if(crc_errors[0] || crc_errors[1] || preamble_errors[0] || preamble_errors[1])$fatal(1,"MAC errors");
        expect_drop=1;corrupt=1;send(17);corrupt=0;
        if(crc_errors[1]!=1)$fatal(1,"Corruption did not raise CRC error");
        inject_error=1;send(17);inject_error=0;
        destination=9002;send(17);destination=9001;
        send(2200);
        expect_drop=0;send(17);
        $display("PASS actual LiteEth: 8 valid UDP packets; CRC corruption, RX_ER, wrong UDP port and oversized frame rejected; hardware ARP, tail lanes, RX backpressure, 100/125 MHz crossings");$finish;
    end
    initial begin #1000000;$fatal(1,"timeout packets=%d",packets);end
endmodule
