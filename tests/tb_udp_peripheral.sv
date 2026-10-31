`timescale 1ns/1ps
module tb_udp_peripheral;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,req_valid=0,req_write=0,resp_ready=0;
    wire req_ready,resp_valid,resp_error;
    reg [31:0] req_addr=0,req_wdata=0;
    reg [3:0] req_wstrb=15;
    wire [31:0] resp_rdata;
    reg rx_valid=0,rx_last=0;
    wire rx_ready;
    reg [31:0] rx_data=0,rx_ip_address=32'hc0a80164;
    reg [3:0] rx_last_be=0,rx_error=0;
    reg [15:0] rx_src_port=9002,rx_dst_port=9001,rx_length=0;
    wire tx_valid,tx_last;
    reg tx_ready=0;
    wire [31:0] tx_data,tx_ip_address;
    wire [15:0] tx_src_port,tx_dst_port,tx_length;
    wire [3:0] tx_last_be,tx_error;
    wire rx_pending,tx_busy;
    wire [31:0] rx_drop_count,rx_bad_count;
    tiny3tpu_udp_peripheral dut(.*);
    reg [31:0] value;
    integer i,j,checks=0,bad_cases=0;
    reg stalled_tx=0;
    reg [120:0] held_tx;
    wire [120:0] tx_signals={tx_data,tx_last,tx_last_be,tx_error,
                             tx_src_port,tx_dst_port,tx_ip_address,tx_length};
    // Observe every cycle, including stalls while the CPU accesses registers.
    always @(posedge clk) begin
        if(rst) stalled_tx<=0;
        else begin
            if(stalled_tx && (!tx_valid || tx_signals!==held_tx))
                $fatal(1,"TX payload/tail/metadata changed under backpressure");
            stalled_tx<=tx_valid && !tx_ready;
            held_tx<=tx_signals;
        end
    end
    task bus;
        input wr;input [31:0] addr,data;input [3:0] strb;input error;
        begin
            @(negedge clk);req_valid=1;req_write=wr;req_addr=addr;req_wdata=data;req_wstrb=strb;
            while(!req_ready) @(negedge clk);
            @(posedge clk);#1;
            @(negedge clk);req_valid=0;
            while(!resp_valid) @(negedge clk);
            if(resp_error!==error) $fatal(1,"MMIO error addr=%h got=%b wanted=%b",addr,resp_error,error);
            value=resp_rdata;
            // Deliberately hold every response to check ready/valid ownership.
            repeat(2) begin @(posedge clk);#1;
                if(!resp_valid || resp_rdata!==value || resp_error!==error || req_ready)
                    $fatal(1,"Response changed under backpressure");
            end
            @(negedge clk);resp_ready=1;
            @(posedge clk);#1;
            @(negedge clk);resp_ready=0;checks=checks+1;
        end
    endtask
    task wr;input [12:0] addr;input [31:0] data;
        begin bus(1,32'h20004000+addr,data,15,0);end
    endtask
    task rd;input [12:0] addr;input [31:0] expected;
        begin bus(0,32'h20004000+addr,0,15,0);
            if(value!==expected)$fatal(1,"Read %h got=%h wanted=%h",addr,value,expected);
        end
    endtask
    function [31:0] pattern;input integer index;
        begin pattern={8'((index+3)%256),8'((index+2)%256),8'((index+1)%256),8'(index%256)};end
    endfunction
    task receive_packet;input integer count, declared, corrupt;
        integer k;
        begin
            for(k=0;k<count;k=k+4) begin
                @(negedge clk);rx_valid=1;rx_data=pattern(k);rx_length=declared;
                rx_last=(k+4>=count);rx_last_be=rx_last ? (1<<((count-1)%4)) : 0;
                rx_error=(corrupt && k==0) ? 1 : 0;
                @(posedge clk);#1;
            end
            @(negedge clk);rx_valid=0;rx_last=0;rx_error=0;
        end
    endtask
    task transmit_packet;input integer count;
        integer k;
        reg [120:0] held;
        begin
            for(k=0;k<count;k=k+4) begin
                while(!tx_valid) begin @(posedge clk);#1;end
                held=tx_signals;
                repeat(3)begin @(posedge clk);#1;
                    if(!tx_valid || tx_signals!==held)$fatal(1,"TX payload/tail/metadata changed while stalled");
                end
                for(j=0;j<4 && k+j<count;j=j+1)
                    if(tx_data[j*8+:8]!==8'((k+j)%256))$fatal(1,"TX byte mismatch %d",k+j);
                if(tx_length!==count || tx_ip_address!==32'hc0a80164 || tx_src_port!==9001 || tx_dst_port!==9002 || tx_error!=0)
                    $fatal(1,"TX metadata mismatch");
                if(tx_last!==(k+4>=count) || (tx_last && tx_last_be!==(1<<((count-1)%4))))
                    $fatal(1,"TX length/last mismatch");
                @(negedge clk);tx_ready=1;
                @(posedge clk);#1;
                @(negedge clk);tx_ready=0;
            end
            if(tx_busy || tx_valid)$fatal(1,"TX did not finish");
        end
    endtask
    initial begin
        repeat(3) @(posedge clk);
        @(negedge clk);rst=0;
        rd('h28,32'h10000);rd(0,2);
        bus(0,32'h40000000,0,15,1);bus(0,32'h20004001,0,15,1);
        bus(0,32'h20004400,0,15,1);bus(1,32'h20004000,1,15,1);
        // RX publication, metadata, exact tail sizes and capacity boundary.
        for(i=1;i<=4;i=i+1)begin
            receive_packet(i,i,0);rd(0,3);rd(4,i);rd(8,32'hc0a80164);
            rd('hc,{16'd9001,16'd9002});rd('h400,32'h03020100);wr('h1c,1);
        end
        receive_packet(1472,1472,0);
        for(i=0;i<1472;i=i+4)rd('h400+i,pattern(i));
        receive_packet(8,8,0);rd('h20,1);rd('h400,32'h03020100);wr('h1c,1);
        receive_packet(8,8,1);rd('h24,1);
        receive_packet(8,9,0);rd('h24,2);
        receive_packet(1476,1476,0);rd('h24,3);
        if(rx_pending)$fatal(1,"Bad RX published");
        wr('h1c,4);rd('h20,0);rd('h24,0);rd(0,2);
        // Only one-hot last-byte encodings are legal. A bad tail must not
        // publish any partial packet and must not poison the following packet.
        for(i=0;i<16;i=i+1) if(i!=1 && i!=2 && i!=4 && i!=8)begin
            @(negedge clk);rx_valid=1;rx_last=1;rx_length=4;
            rx_data=32'hfadedbad;rx_last_be=i;
            @(posedge clk);#1;
            @(negedge clk);rx_valid=0;rx_last=0;
            bad_cases=bad_cases+1;rd('h24,bad_cases);
            if(rx_pending)$fatal(1,"Illegal last_be published a packet");
        end
        // Change each metadata field after the first beat. For the length
        // case the final length matches the received bytes, so only metadata
        // consistency (not final byte counting) can catch the malformed packet.
        for(i=0;i<4;i=i+1)begin
            @(negedge clk);rx_valid=1;rx_last=0;rx_last_be=0;rx_data=pattern(0);
            rx_length=(i==0)?12:8;
            @(posedge clk);#1;
            @(negedge clk);rx_last=1;rx_last_be=8;rx_data=pattern(4);rx_length=8;
            if(i==1)rx_src_port=9003;
            if(i==2)rx_dst_port=9000;
            if(i==3)rx_ip_address=32'hc0a80165;
            @(posedge clk);#1;
            @(negedge clk);rx_valid=0;rx_last=0;rx_src_port=9002;
            rx_dst_port=9001;rx_ip_address=32'hc0a80164;
            bad_cases=bad_cases+1;rd('h24,bad_cases);
            if(rx_pending)$fatal(1,"Changed metadata published a packet");
        end
        receive_packet(2,2,0);rd(4,2);wr('h1c,1);wr('h1c,4);
        // RELEASE on the first beat frees the held packet in time to accept
        // the replacement, including a single-beat packet at that same edge.
        receive_packet(4,4,0);
        fork
            wr('h1c,1);
            begin
                @(negedge clk);rx_valid=1;rx_last=1;rx_last_be=8;
                rx_length=4;rx_data=32'h1234abcd;
                @(posedge clk);#1;
                @(negedge clk);rx_valid=0;rx_last=0;
            end
        join
        rd(0,3);rd(4,4);rd('h400,32'h1234abcd);rd('h20,0);
        // A packet that started while the slot was occupied remains discarded
        // even if RELEASE happens between its first and last beats.
        @(negedge clk);rx_valid=1;rx_last=0;rx_last_be=0;rx_length=8;rx_data=32'hdeadbeef;
        @(posedge clk);#1;
        @(negedge clk);rx_valid=0;
        rd('h400,32'h1234abcd);wr('h1c,1);
        @(negedge clk);rx_valid=1;rx_last=1;rx_last_be=8;rx_data=32'hbad0cafe;
        @(posedge clk);#1;
        @(negedge clk);rx_valid=0;rx_last=0;
        rd('h20,1);rd('h24,0);
        if(rx_pending)$fatal(1,"Mid-packet release published a discarded suffix");
        receive_packet(3,3,0);rd(4,3);rd('h400,pattern(0));wr('h1c,1);wr('h1c,4);
        // An invalid combined command is atomic: neither release nor counter
        // clear may happen when the requested TX commit is rejected.
        receive_packet(4,5,0);receive_packet(4,4,0);receive_packet(4,4,0);
        rd('h20,1);rd('h24,1);wr('h10,0);
        bus(1,32'h2000401c,7,15,1);
        rd(0,15);rd('h20,1);rd('h24,1);rd('h400,pattern(0));
        if(tx_busy || tx_valid)$fatal(1,"Invalid combined command started TX");
        wr('h10,4);bus(1,32'h2000401c,15,15,1); // Reserved command bit.
        rd(0,15);rd('h20,1);rd('h24,1);
        if(tx_busy || tx_valid)$fatal(1,"Reserved command bit started TX");
        wr('h1c,1);wr('h1c,4);
        // Simultaneous CPU RX and independent TX buffers; partial writes.
        for(i=0;i<1472;i=i+4)wr('h1000+i,pattern(i));
        bus(1,32'h20005000,32'hffffffff,0,0);
        bus(1,32'h20005000,32'hffffff00,1,0);
        wr('h14,32'hc0a80164);wr('h18,{16'd9002,16'd9001});
        for(i=1;i<=4;i=i+1)begin
            wr('h10,i);wr('h1c,2);transmit_packet(i);
        end
        wr('h10,1472);wr('h1c,2);
        bus(1,32'h20005000,0,15,1);bus(1,32'h20004014,0,15,1);
        bus(1,32'h2000401c,2,15,1);
        receive_packet(7,7,0);rd(4,7);
        bus(1,32'h2000401c,3,15,1); // Busy commit must not release RX.
        if(!rx_pending)$fatal(1,"Rejected busy commit released RX");
        rd(4,7);rd('h400,pattern(0));
        transmit_packet(1472);wr('h1c,1);
        wr('h10,0);bus(1,32'h2000401c,2,15,1);
        wr('h10,1473);bus(1,32'h2000401c,2,15,1);
        // Reset during a held TX beat and partial RX; no stale packet escapes.
        wr('h10,8);wr('h1c,2);
        @(negedge clk);rx_valid=1;rx_last=0;rx_length=8;rx_data=32'hbad;
        @(posedge clk);#1;
        @(negedge clk);rst=1;rx_valid=0;
        repeat(3)@(posedge clk);
        @(negedge clk);rst=0;
        rd(0,2);rd('h20,0);rd('h24,0);
        if(tx_valid)$fatal(1,"Stale TX after reset");
        receive_packet(5,5,0);rd(4,5);wr('h1c,1);
        // A reset cancels a held BRAM MMIO response and its RX ownership.
        receive_packet(4,4,0);
        @(negedge clk);req_valid=1;req_write=0;req_addr=32'h20004400;resp_ready=0;
        @(posedge clk);#1;
        @(negedge clk);req_valid=0;
        repeat(3)begin @(posedge clk);#1;
            if(!resp_valid || resp_error || resp_rdata!==pattern(0) || req_ready)
                $fatal(1,"Expected held RX MMIO response before reset");
        end
        @(negedge clk);rst=1;
        repeat(3)begin @(posedge clk);#1;
            if(resp_valid || rx_pending || tx_valid || rx_ready)
                $fatal(1,"Reset retained a response/packet");
        end
        @(negedge clk);rst=0;resp_ready=1;
        repeat(3)begin @(posedge clk);#1;
            if(resp_valid)$fatal(1,"Stale MMIO response escaped after reset");
        end
        @(negedge clk);resp_ready=0;
        rd('h28,32'h10000);rd(0,2);receive_packet(4,4,0);rd('h400,pattern(0));wr('h1c,1);
        $display("PASS UDP packet peripheral: %0d checked MMIO transactions, RX/TX tails, metadata, MTU, atomic commands, release races, backpressure, drops and reset",checks);
        $finish;
    end
    initial begin #2000000;$fatal(1,"Timeout");end
endmodule
