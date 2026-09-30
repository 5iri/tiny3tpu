`timescale 1ns/1ps
module tb #(parameter PIPELINED_DECODE=0);
    reg clk=0, rst=1;
    always #5 clk=~clk;
    wire fault, req, req_write, resp_ready;
    wire [31:0] addr, wdata;
    wire [3:0] strb;
    reg req_ready=0, resp_valid=0, resp_error=0;
    reg [31:0] rdata=0;
    vexriscv_tpu_soc #(.BOOT_WORDS(64),.PIPELINED_DECODE(PIPELINED_DECODE)) dut (
        .clk(clk), .rst(rst), .ready_to_run(!rst), .uart_rx(1'b1), .uart_tx(),
        .fault(fault), .pc_debug(), .ext_req_valid(req), .ext_req_ready(req_ready),
        .ext_req_write(req_write), .ext_req_addr(addr), .ext_req_wdata(wdata),
        .ext_req_wstrb(strb), .ext_resp_valid(resp_valid), .ext_resp_ready(resp_ready),
        .ext_resp_rdata(rdata), .ext_resp_error(resp_error),
        .report_valid(), .report_data(), .exit_valid(), .exit_code()
    );
    task data_start(input bit wr, input [31:0] a, data, input [3:0] sel);
        @(negedge clk);
        dut.cpu.dBusWishbone_CYC=1; dut.cpu.dBusWishbone_STB=1;
        dut.cpu.dBusWishbone_WE=wr; dut.cpu.dBusWishbone_ADR=a>>2;
        dut.cpu.dBusWishbone_DAT_MOSI=data; dut.cpu.dBusWishbone_SEL=sel;
    endtask
    task data_finish(input bit error, input [31:0] expected, input bit check_data);
        do @(posedge clk); while (!(dut.cpu.dBusWishbone_ACK || dut.cpu.dBusWishbone_ERR));
        if (dut.cpu.dBusWishbone_ERR !== error || dut.cpu.dBusWishbone_ACK === error)
            $fatal(1,"ACK/ERR exclusivity or incorrect response");
        if (check_data && dut.cpu.dBusWishbone_DAT_MISO !== expected)
            $fatal(1,"data got %h expected %h",dut.cpu.dBusWishbone_DAT_MISO,expected);
        @(negedge clk); dut.cpu.dBusWishbone_CYC=0; dut.cpu.dBusWishbone_STB=0;
    endtask
    integer n, i_count=0, d_count=0, last_owner=-1;
    initial begin
        dut.cpu.iBusWishbone_CYC=0; dut.cpu.iBusWishbone_STB=0;
        dut.cpu.iBusWishbone_WE=0; dut.cpu.iBusWishbone_ADR=0;
        dut.cpu.iBusWishbone_SEL=15; dut.cpu.iBusWishbone_DAT_MOSI=0;
        dut.cpu.iBusWishbone_CTI=0; dut.cpu.iBusWishbone_BTE=0;
        dut.cpu.dBusWishbone_CYC=0; dut.cpu.dBusWishbone_STB=0;
        dut.cpu.dBusWishbone_WE=0; dut.cpu.dBusWishbone_ADR=0;
        dut.cpu.dBusWishbone_SEL=15; dut.cpu.dBusWishbone_DAT_MOSI=0;
        dut.cpu.dBusWishbone_CTI=0; dut.cpu.dBusWishbone_BTE=0;
        repeat(4) @(negedge clk); rst=0;
        for(n=0;n<16;n=n+1) begin
            data_start(1,32'h80000000+4*n,32'h12340000+n,15);
            data_finish(0,0,0);
        end
        // Both masters hold CYC/STB across all beats; addresses change only
        // after ACK. Check no beat repeats, wrong-owner ACK, or starvation.
        @(negedge clk);
        dut.cpu.iBusWishbone_CYC=1; dut.cpu.iBusWishbone_STB=1;
        dut.cpu.iBusWishbone_ADR=32'h80000000>>2; dut.cpu.iBusWishbone_CTI=2;
        dut.cpu.dBusWishbone_CYC=1; dut.cpu.dBusWishbone_STB=1;
        dut.cpu.dBusWishbone_WE=0; dut.cpu.dBusWishbone_ADR=32'h80000000>>2;
        while (i_count<16 || d_count<16) begin
            @(posedge clk);
            if(dut.cpu.iBusWishbone_ERR || dut.cpu.dBusWishbone_ERR) $fatal(1,"burst error");
            if(dut.cpu.iBusWishbone_ACK && dut.cpu.dBusWishbone_ACK) $fatal(1,"two owners");
            if(dut.cpu.iBusWishbone_ACK) begin
                if (last_owner==0 || dut.cpu.iBusWishbone_DAT_MISO !== 32'h12340000+i_count)
                    $fatal(1,"instruction refill data/fairness");
                last_owner=0; i_count=i_count+1;
                @(negedge clk); dut.cpu.iBusWishbone_ADR=dut.cpu.iBusWishbone_ADR+1;
                if(i_count==15) dut.cpu.iBusWishbone_CTI=7;
                if(i_count==16) begin dut.cpu.iBusWishbone_CYC=0;dut.cpu.iBusWishbone_STB=0;end
            end else if(dut.cpu.dBusWishbone_ACK) begin
                if (last_owner==1 || dut.cpu.dBusWishbone_DAT_MISO !== 32'h12340000+d_count)
                    $fatal(1,"data burst data/fairness");
                last_owner=1; d_count=d_count+1;
                @(negedge clk); dut.cpu.dBusWishbone_ADR=dut.cpu.dBusWishbone_ADR+1;
                if(d_count==16) begin dut.cpu.dBusWishbone_CYC=0;dut.cpu.dBusWishbone_STB=0;end
            end
        end
        data_start(1,32'h80000000,32'habcdef99,4'b0101); data_finish(0,0,0);
        data_start(0,32'h80000000,0,15); data_finish(0,32'h12cd0099,1);
        // Request and response backpressure; controller CSR remains reachable
        // before DDR initialization. An external error must not become ACK.
        for(n=0;n<8;n=n+1) begin
            req_ready=0;
            data_start(n[0],n[1]?32'hf0000040:32'h40000020,32'habcdef00+n,4'b0101);
            wait(req);
            repeat(7) begin
                @(negedge clk);
                if (!req || req_write!==n[0] || wdata!==32'habcdef00+n || strb!==4'b0101 ||
                    addr!==(n[1]?32'hf0000040:32'h40000020)) $fatal(1,"request changed while stalled");
                if(dut.cpu.dBusWishbone_ACK || dut.cpu.dBusWishbone_ERR) $fatal(1,"early ACK");
            end
            req_ready=1; @(negedge clk); req_ready=0;
            repeat(9) @(negedge clk);
            rdata=32'hfeed0000+n;resp_error=(n==7);resp_valid=1;
            @(posedge clk);if(!resp_ready) $fatal(1,"missing response ready");
            @(negedge clk);resp_valid=0;
            data_finish(n==7,32'hfeed0000+n,1);
        end
        if(!fault) $fatal(1,"bus error not latched");
        rst=1;repeat(3) @(negedge clk);rst=0;
        if(fault) $fatal(1,"fault did not reset");
        data_start(0,32'h30000000,0,15);data_finish(1,0,0);
        if(!fault) $fatal(1,"unmapped access not latched");
        $display("PASS VexRiscv interconnect: concurrent bursts, fair arbitration, byte enables, stable stalled requests, CSR/DDR, ERR and reset");
        $finish;
    end
    initial begin #100000; $fatal(1,"timeout");end
endmodule
