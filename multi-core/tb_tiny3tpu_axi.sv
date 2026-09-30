`timescale 1ns/1ps

// Black-box firmware-register and AXI4-Lite regression. No DUT internals.
module tb_tiny3tpu_axi;
    reg s_axi_aclk = 0;
    always #5 s_axi_aclk = ~s_axi_aclk;
    reg s_axi_aresetn = 0;
    reg [7:0] s_axi_awaddr = 0, s_axi_araddr = 0;
    reg [2:0] s_axi_awprot = 0, s_axi_arprot = 0;
    reg s_axi_awvalid = 0, s_axi_wvalid = 0, s_axi_bready = 0;
    reg s_axi_arvalid = 0, s_axi_rready = 0;
    reg [31:0] s_axi_wdata = 0;
    reg [3:0] s_axi_wstrb = 0;
    wire s_axi_awready, s_axi_wready, s_axi_bvalid;
    wire s_axi_arready, s_axi_rvalid;
    wire [1:0] s_axi_bresp, s_axi_rresp;
    wire [31:0] s_axi_rdata;

    tiny3tpu_axi dut (.*);

    localparam [7:0] CTRL=0, CFG=4, DATA=8, CRDCFG=12,
                     STATUS=16, LO=20, HI=24;
    integer writes=0, reads=0, cells=0, negatives=0;
    integer a[0:1][0:3][0:3], b[0:1][0:3][0:3];
    integer expected[0:1][0:3][0:3];
    integer c, i, j, k, pass, lane;
    reg [31:0] value, merged;

    initial begin
        #2000000;
        $fatal(1, "global AXI regression watchdog expired");
    end

    task automatic send_aw(input [7:0] addr, input integer delay_cycles);
        integer n;
        begin
            repeat(delay_cycles) @(negedge s_axi_aclk);
            @(negedge s_axi_aclk);
            s_axi_awaddr=addr; s_axi_awvalid=1;
            n=0;
            do begin
                @(posedge s_axi_aclk); n=n+1;
                if(n>100) $fatal(1,"AW timeout addr=%h",addr);
            end while(s_axi_awready !== 1'b1);
            @(negedge s_axi_aclk);
            s_axi_awvalid=0; s_axi_awaddr=8'hfc;
        end
    endtask

    task automatic send_w(input [31:0] data, input [3:0] strb,
                          input integer delay_cycles);
        integer n;
        begin
            repeat(delay_cycles) @(negedge s_axi_aclk);
            @(negedge s_axi_aclk);
            s_axi_wdata=data; s_axi_wstrb=strb; s_axi_wvalid=1;
            n=0;
            do begin
                @(posedge s_axi_aclk); n=n+1;
                if(n>100) $fatal(1,"W timeout data=%h",data);
            end while(s_axi_wready !== 1'b1);
            @(negedge s_axi_aclk);
            s_axi_wvalid=0; s_axi_wdata=32'hbad0dead; s_axi_wstrb=0;
        end
    endtask

    // order 0: simultaneous, 1: AW first, 2: W first.
    task automatic wr(input [7:0] addr, input [31:0] data,
                      input [3:0] strb, input integer order,
                      input integer stall, input [1:0] response);
        integer n;
        begin
            fork
                send_aw(addr, order==2 ? 5 : 0);
                send_w(data, strb, order==1 ? 5 : 0);
            join
            n=0;
            while(s_axi_bvalid !== 1'b1) begin
                @(negedge s_axi_aclk); n=n+1;
                if(n>100) $fatal(1,"B timeout addr=%h",addr);
            end
            repeat(stall+1) begin
                if(s_axi_bvalid !== 1'b1 || s_axi_bresp !== response)
                    $fatal(1,"B response/stability addr=%h resp=%b expected=%b",addr,s_axi_bresp,response);
                @(negedge s_axi_aclk);
            end
            s_axi_bready=1;
            @(negedge s_axi_aclk); s_axi_bready=0;
            if(s_axi_bvalid !== 1'b0) $fatal(1,"duplicate B response");
            writes=writes+1;
        end
    endtask

    task automatic rd(input [7:0] addr, input integer stall,
                      input [1:0] response, output [31:0] data);
        integer n;
        begin
            @(negedge s_axi_aclk);
            s_axi_araddr=addr; s_axi_arvalid=1;
            n=0;
            do begin
                @(posedge s_axi_aclk); n=n+1;
                if(n>100) $fatal(1,"AR timeout addr=%h",addr);
            end while(s_axi_arready !== 1'b1);
            @(negedge s_axi_aclk);
            s_axi_arvalid=0; s_axi_araddr=8'hfc;
            n=0;
            while(s_axi_rvalid !== 1'b1) begin
                @(negedge s_axi_aclk); n=n+1;
                if(n>100) $fatal(1,"R timeout addr=%h",addr);
            end
            data=s_axi_rdata;
            repeat(stall+1) begin
                if(s_axi_rvalid !== 1'b1 || s_axi_rresp !== response || s_axi_rdata !== data)
                    $fatal(1,"R response/stability addr=%h data=%h resp=%b",addr,s_axi_rdata,s_axi_rresp);
                @(negedge s_axi_aclk);
            end
            s_axi_rready=1;
            @(negedge s_axi_aclk); s_axi_rready=0;
            if(s_axi_rvalid !== 1'b0) $fatal(1,"duplicate R response");
            reads=reads+1;
        end
    endtask

    task automatic check_reg(input [7:0] addr, input [31:0] want);
        reg [31:0] got;
        begin
            rd(addr,3,0,got);
            if(got !== want) $fatal(1,"register %h got=%h expected=%h",addr,got,want);
        end
    endtask

    task automatic reset_bus;
        begin
            @(negedge s_axi_aclk);
            s_axi_aresetn=0;
            s_axi_awvalid=0; s_axi_wvalid=0; s_axi_bready=0;
            s_axi_arvalid=0; s_axi_rready=0;
            repeat(4) @(negedge s_axi_aclk);
            if(s_axi_bvalid !== 0 || s_axi_rvalid !== 0)
                $fatal(1,"reset did not clear responses");
            s_axi_aresetn=1;
            repeat(2) @(negedge s_axi_aclk);
            check_reg(CTRL,0); check_reg(CFG,0); check_reg(DATA,0);
            check_reg(CRDCFG,0); check_reg(STATUS,0);
            check_reg(LO,0); check_reg(HI,0);
        end
    endtask

    function automatic [31:0] cfg_word(input integer core_id,
                                      input integer row_id,
                                      input integer col_id,
                                      input integer bank);
        cfg_word=(core_id<<8)|(row_id<<16)|(col_id<<24)|bank;
    endfunction

    task automatic load_cell(input integer core_id, row_id, col_id, bank,
                             input integer datum);
        begin
            wr(CFG,cfg_word(core_id,row_id,col_id,bank),15,(row_id+col_id)%3,0,0);
            wr(DATA,datum,15,(core_id+col_id)%3,0,0);
            wr(CTRL,2,1,(bank+row_id)%3,1,0);
            wr(CTRL,0,15,0,0,0); // firmware deassert write
        end
    endtask

    task automatic run_and_compare;
        integer core_id, row_id, col_id, polls;
        reg [31:0] status_word, low_word, high_word;
        reg signed [63:0] result_word, reference_word;
        begin
            wr(CTRL,1,1,0,0,0);
            rd(STATUS,0,0,status_word);
            if(status_word[0] !== 1) $fatal(1,"START did not assert BUSY");
            polls=0;
            while(status_word[0] !== 0) begin
                rd(STATUS,0,0,status_word); polls=polls+1;
                if(polls>200) $fatal(1,"accelerator did not finish");
            end
            for(core_id=0;core_id<2;core_id=core_id+1)
                for(row_id=0;row_id<4;row_id=row_id+1)
                    for(col_id=0;col_id<4;col_id=col_id+1) begin
                        wr(CRDCFG,cfg_word(core_id,row_id,col_id,0),15,col_id%3,0,0);
                        wr(CTRL,4,1,row_id%3,0,0);
                        wr(CTRL,0,15,0,0,0);
                        rd(LO,2,0,low_word); rd(HI,3,0,high_word);
                        result_word={high_word,low_word};
                        reference_word=expected[core_id][row_id][col_id];
                        if(result_word !== reference_word)
                            $fatal(1,"C core=%0d row=%0d col=%0d got=%0d (%h) expected=%0d",
                                   core_id,row_id,col_id,result_word,result_word,reference_word);
                        cells=cells+1;
                        if(reference_word<0) negatives=negatives+1;
                    end
        end
    endtask

    initial begin
        reset_bus();
        // All byte lanes, retained bytes, and a zero-strobe write.
        for(i=4;i<=12;i=i+4) begin
            wr(i,32'h12345678,15,0,4,0);
            merged=32'h12345678;
            for(lane=0;lane<4;lane=lane+1) begin
                wr(i,32'hfedcba98,1<<lane,lane%3,2,0);
                merged=(merged & ~(32'hff<<(8*lane))) | (32'hfedcba98 & (32'hff<<(8*lane)));
                check_reg(i,merged);
            end
            wr(i,0,0,2,2,0); check_reg(i,merged);
        end
        wr(CTRL,1,0,1,0,0); check_reg(STATUS,0);
        wr(CTRL,1,14,2,0,0); check_reg(STATUS,0);
        check_reg(CTRL,0);
        // Invalid and unaligned addresses must not alias real registers.
        wr(8'hfc,32'hffffffff,15,1,3,2);
        rd(8'hfc,4,2,value);
        wr(8'h05,32'hffffffff,15,2,3,2);
        rd(8'h05,4,2,value);
        check_reg(CFG,32'hfedcba98);
        for(i=16;i<=24;i=i+4) wr(i,32'hffffffff,15,0,0,2);
        check_reg(STATUS,0); check_reg(LO,0); check_reg(HI,0);
        // Reset discards each independent half of a write transaction.
        send_aw(DATA,0); reset_bus();
        send_w(32'hffffffff,15,0); reset_bus();
        // Reset discards stalled responses on both channels.
        fork send_aw(DATA,0); send_w(32'hdeadbeef,15,0); join
        repeat(5) @(negedge s_axi_aclk);
        if(s_axi_bvalid !== 1) $fatal(1,"missing pending B before reset");
        s_axi_araddr=DATA; s_axi_arvalid=1;
        do @(posedge s_axi_aclk); while(s_axi_arready !== 1);
        @(negedge s_axi_aclk); s_axi_arvalid=0;
        repeat(5) @(negedge s_axi_aclk);
        if(s_axi_rvalid !== 1) $fatal(1,"missing pending R before reset");
        reset_bus();

        for(pass=0;pass<2;pass=pass+1) begin
            for(c=0;c<2;c=c+1)
                for(i=0;i<4;i=i+1)
                    for(j=0;j<4;j=j+1) begin
                        a[c][i][j]=((i*31+j*17+c*43+pass*29)%256)-128;
                        b[c][i][j]=((i*19+j*47+c*61+pass*37)%256)-128;
                        load_cell(c,i,j,0,a[c][i][j]);
                        load_cell(c,i,j,1,b[c][i][j]);
                    end
            // Packed row path replaces the legacy-loaded values. Exercise
            // every byte-strobe combination, independent AW/W ordering and
            // stalled B responses, then compare all matrix outputs.
            if(pass==1) for(lane=0;lane<16;lane=lane+1) begin
                for(c=0;c<2;c=c+1) for(i=0;i<4;i=i+1) begin
                    value=32'h817ffe00 ^ (lane*32'h13271931);
                    wr(8'h40+c*32+i*4,value,lane,lane%3,3,0);
                    for(j=0;j<4;j=j+1)
                        if(lane & (1<<j)) a[c][i][j]=$signed(value[j*8 +: 8]);
                    value=~value;
                    wr(8'h50+c*32+i*4,value,lane,(lane+1)%3,2,0);
                    for(j=0;j<4;j=j+1)
                        if(lane & (1<<j)) b[c][i][j]=$signed(value[j*8 +: 8]);
                end
                // Check each mask before a later mask can overwrite its data.
                for(c=0;c<2;c=c+1) for(i=0;i<4;i=i+1)
                    for(j=0;j<4;j=j+1) begin
                        expected[c][i][j]=0;
                        for(k=0;k<4;k=k+1)
                            expected[c][i][j]+=a[c][i][k]*b[c][k][j];
                    end
                run_and_compare();
            end
            wr(8'h41,32'hffffffff,15,0,0,2);
            rd(8'h40,2,2,value); // packed aperture is write-only
            for(c=0;c<2;c=c+1)
                for(i=0;i<4;i=i+1)
                    for(j=0;j<4;j=j+1) begin
                        expected[c][i][j]=0;
                        for(k=0;k<4;k=k+1)
                            expected[c][i][j]=expected[c][i][j]+a[c][i][k]*b[c][k][j];
                    end
            run_and_compare();
            run_and_compare(); // retained UBUF, fresh accumulation
        end
        if(negatives==0) $fatal(1,"negative sign-extension coverage missing");
        // Busy packed writes must reject without altering retained operands.
        wr(CTRL,1,1,0,0,0);
        wr(8'h40,32'hffffffff,15,0,0,2);
        repeat(100) @(negedge s_axi_aclk);
        run_and_compare();
        // Reset at each of the four serialized byte-store boundaries.
        for(lane=0;lane<4;lane=lane+1) begin
            fork send_aw(8'h40,0); send_w(32'h817f1234,15,0); join
            repeat(lane) @(negedge s_axi_aclk);
            reset_bus();
            for(c=0;c<2;c=c+1) for(i=0;i<4;i=i+1)
                for(j=0;j<4;j=j+1) expected[c][i][j]=0;
            run_and_compare();
        end
        // Reset an active launch, then prove the cleared datapath is usable.
        wr(CTRL,1,1,0,0,0);
        reset_bus();
        for(c=0;c<2;c=c+1)
            for(i=0;i<4;i=i+1)
                for(j=0;j<4;j=j+1) expected[c][i][j]=0;
        run_and_compare();
        $display("PASS tiny3tpu_axi: writes=%0d reads=%0d cells=%0d negative=%0d",writes,reads,cells,negatives);
        $finish;
    end
endmodule
