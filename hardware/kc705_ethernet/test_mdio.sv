`timescale 1ns/1ps
module test_mdio;
    reg clk=0,rst=1;always #5 clk=~clk;
    wire phy_rst_n,mdc,configured,link_up,mdio_fault;wire [15:0] basic_status;
    tri1 mdio;reg phy_drive=0,phy_bit=1,respond=1;reg [15:0] status=16'h0024;
    assign mdio=phy_drive ? phy_bit : 1'bz;
    kc705_phy_mdio #(.RESET_CYCLES(8),.POLL_CYCLES(30)) dut(
        .clk(clk),.rst(rst),.phy_rst_n(phy_rst_n),.mdc(mdc),.mdio(mdio),
        .configured(configured),.link_up(link_up),.mdio_fault(mdio_fault),.basic_status(basic_status));
    integer bitpos=0,writes=0,reads=0;reg reading=0;reg [63:0] captured=0;
    always @(negedge mdc) begin
        phy_drive=respond && reading && bitpos>=47;
        phy_bit=bitpos==47 ? 0 : ((status>>(63-bitpos))&1);
    end
    always @(posedge mdc) if(!rst)begin
        captured={captured[62:0],mdio};
        if(bitpos==35) reading=captured[1:0]==2'b10;
        if(reading && bitpos==46 && mdio!==1'b1)$fatal(1,"Read TA was not tri-stated");
        if(bitpos==63)begin
            if(captured[63:32]!=32'hffffffff || captured[31:30]!=1 || captured[27:23]!=7)
                $fatal(1,"Clause22 preamble/start/PHY address mismatch %h",captured);
            if(reading)begin
                if(captured[22:18]!=1)$fatal(1,"Expected BMSR double-read");reads=reads+1;
            end else begin
                case(writes%3)
                    0: if(captured[22:18]!=4 || captured[15:0]!=16'h0001)$fatal(1,"10/100 advertisement not disabled");
                    1: if(captured[22:18]!=9 || captured[15:0]!=16'h0200)$fatal(1,"Missing gigabit full-duplex advertisement");
                    2: if(captured[22:18]!=0 || captured[15:0]!=16'h1200)$fatal(1,"Missing auto-negotiation restart");
                endcase
                if(captured[29:28]!=1 || captured[17:16]!=2)$fatal(1,"Write opcode/TA mismatch");
                writes=writes+1;
            end
            bitpos=0;reading=0;
        end else bitpos=bitpos+1;
    end
    initial begin
        #30;if(phy_rst_n!==0)$fatal(1,"PHY reset not asserted");rst=0;
        wait(configured);#1;
        if(writes!=3 || reads!=2 || !link_up || basic_status!=16'h0024 || mdio_fault)$fatal(1,"Initial management status mismatch");
        status=16'h0020;wait(!link_up);#1;if(!configured || mdio_fault)$fatal(1,"Link-down poll failed");
        respond=0;wait(mdio_fault);#1;if(configured || link_up)$fatal(1,"Missing PHY acknowledgement not reported");
        respond=1;status=16'h0024;wait(link_up);#1;
        rst=1;repeat(3)@(posedge clk);#1;if(phy_rst_n || configured || link_up)$fatal(1,"Reset did not clear status");
        $display("PASS MDIO: address7, gigabit writes, released read TA, BMSR double-read, link loss, missing PHY, recovery and reset");$finish;
    end
    initial begin #2000000;$fatal(1,"MDIO timeout writes=%d reads=%d",writes,reads);end
endmodule
