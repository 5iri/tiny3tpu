`timescale 1ns/1ps
module test_init #(parameter integer VIDEO_720P=0, CLOCK_HZ=VIDEO_720P ? 74250000 : 25200000);
    reg clk=0, reset=1;
    always #(500000000.0/CLOCK_HZ) clk=~clk;
    tri1 scl, sda;
    reg slave_sda_low=0, slave_scl_low=0, stuck_sda=0;
    assign sda=(slave_sda_low || stuck_sda) ? 1'b0 : 1'bz;
    assign scl=slave_scl_low ? 1'b0 : 1'bz;
    wire configured,error,mux_reset_n;
    kc705_hdmi_init #(.CLOCK_HZ(CLOCK_HZ),.VIDEO_720P(VIDEO_720P),.STARTUP_MS(0),.POLL_MS(1),
        .STRETCH_TIMEOUT_MS(1),.LOCK_POLL_LIMIT(3)) dut (
        .clk(clk),.reset(reset),.scl(scl),.sda(sda),
        .mux_reset_n(mux_reset_n),.configured(configured),.error(error)
    );

    // Behavioral PCA9548 + ADV7511 model observes only resolved bus pins.
    // No DUT internals are used to acknowledge bytes or generate read data.
    localparam RX=0, ACK=1, TX=2, MASTER_NAK=3, WAIT_STOP=4;
    integer mode=WAIT_STOP, bits=0, byte_number=0, device=0;
    reg [7:0] incoming=0, pointer=0, outgoing=0, mux=0;
    reg [7:0] regs[0:255];
    reg ack_clocked=0, byte_ack=0, reading=0, hpd=1, pll=1;
    reg persistent_nak=0, suppress_model=0;
    integer inject_naks=0, nak_byte=-1, observed_naks=0;
    integer starts=0, stops=0, read_count=0, writes=0, mux_writes=0;
    integer configure_count=0, i;
    reg [15:0] written[0:4095];
    time last_rise=0, last_fall=0;
    integer clock_edges=0;

    always @(negedge mux_reset_n) begin
        mux=0; mode=WAIT_STOP; slave_sda_low=0;
    end
    always @(negedge sda) begin
        if (scl===1'b1 && !reset && !suppress_model) begin
            mode=RX; bits=0; byte_number=0; incoming=0;
            ack_clocked=0; reading=0; starts=starts+1;
        end
    end
    always @(posedge sda) begin
        if (scl===1'b1 && !reset && !suppress_model) begin
            mode=WAIT_STOP; slave_sda_low=0; stops=stops+1;
        end
    end
    always @(posedge scl) begin
        if (!reset && !suppress_model) begin
            if (last_fall && $time-last_fall<4700)
                $fatal(1,"I2C low interval too short: %0t",$time-last_fall);
            if (last_rise && $time-last_rise<10000)
                $fatal(1,"I2C exceeds 100 kHz: %0t",$time-last_rise);
            last_rise=$time; clock_edges=clock_edges+1;
            case(mode)
                RX: begin
                    incoming={incoming[6:0],sda};
                    if (bits==7) begin
                        byte_ack=1;
                        if (byte_number==0) begin
                            if (incoming==8'he8) device=1;
                            else if ((incoming==8'h72 || incoming==8'h73) && mux==8'h20) begin
                                device=2; reading=incoming[0];
                            end else begin
                                device=0; byte_ack=0;
                                $fatal(1,"wrong I2C address %02x / mux %02x",incoming,mux);
                            end
                        end
                        if (persistent_nak || (inject_naks>0 && byte_number==nak_byte)) begin
                            byte_ack=0; observed_naks=observed_naks+1;
                            if (inject_naks>0) inject_naks=inject_naks-1;
                        end
                        if (byte_ack) begin
                            if (device==1 && byte_number==1) begin
                                if(incoming!=8'h20) $fatal(1,"wrong mux channel");
                                mux=incoming; mux_writes=mux_writes+1;
                            end
                            if (device==2 && byte_number==1) pointer=incoming;
                            if (device==2 && byte_number==2) begin
                                written[writes]={pointer,incoming}; writes=writes+1;
                                if(pointer==8'h96) regs[pointer]=regs[pointer]&~incoming;
                                else regs[pointer]=incoming;
                                if(pointer==8'h41) configure_count=configure_count+1;
                            end
                        end
                        bits=0; mode=ACK; ack_clocked=0;
                    end else bits=bits+1;
                end
                ACK: ack_clocked=1;
                TX: begin
                    if(bits==0) begin mode=MASTER_NAK; ack_clocked=0; end
                    else bits=bits-1;
                end
                MASTER_NAK: begin
                    if(sda!==1'b1) $fatal(1,"master must NACK final read byte");
                    mode=WAIT_STOP; read_count=read_count+1;
                end
                default: ;
            endcase
        end
    end
    always @(negedge scl) begin
        if (!reset && !suppress_model) begin
            if(last_rise && $time-last_rise<4000)
                $fatal(1,"I2C high interval too short: %0t",$time-last_rise);
            last_fall=$time;
            case(mode)
                ACK: begin
                    if(!ack_clocked) slave_sda_low=byte_ack;
                    else begin
                        slave_sda_low=0;
                        if(!byte_ack) mode=WAIT_STOP;
                        else if(reading && byte_number==0) begin
                            if(pointer==8'h42) outgoing=hpd ? 8'hd0 : 8'h90;
                            else if(pointer==8'h9e) outgoing=pll ? 8'h10 : 8'h00;
                            else outgoing=regs[pointer];
                            bits=7; mode=TX; slave_sda_low=!outgoing[7];
                        end else begin mode=RX; byte_number=byte_number+1; end
                    end
                end
                TX: slave_sda_low=!outgoing[bits];
                MASTER_NAK, WAIT_STOP: slave_sda_low=0;
                default: ;
            endcase
        end
    end
    always @(posedge clk) begin
        if (!reset) begin
            if (scl!==0 && scl!==1) $fatal(1,"SCL contention");
            if (sda!==0 && sda!==1) $fatal(1,"SDA contention");
            if(configured && error) $fatal(1,"configured and error asserted together");
        end
    end

    task automatic reboot;
        begin
            reset=1; #200; slave_sda_low=0; mode=WAIT_STOP;
            last_rise=0; last_fall=0;
            if(mux_reset_n!==0) $fatal(1,"mux reset not asserted");
            #200; reset=0;
            if(configured || error) $fatal(1,"status not cleared by reset");
        end
    endtask
    task automatic wait_configured;
        integer n;
        begin
            n=0;
            while(!configured && !error && n<CLOCK_HZ/10) begin @(posedge clk); n=n+1; end
            if(!configured || error) $fatal(1,"failed to configure state=%0d n=%0d",dut.state,n);
        end
    endtask
    task automatic check_registers;
        begin
            if(regs['h15]!='h01 || regs['h16]!='h34 || regs['h48]!='h08)
                $fatal(1,"wrong KC705 16-bit input mapping");
            if(regs['h41]!='h10 || regs['haf]!='h06 || regs['h44]!='h11)
                $fatal(1,"power, HDMI or no-audio setup wrong");
            if(regs['h3b]!='hc0 || regs['h3c]!=(VIDEO_720P ? 4 : 1) || regs['h55]!=2 || regs['h56]!=(VIDEO_720P ? 'h20 : 'h10) || regs['h57]!=8)
                $fatal(1,"wrong mode/RGB AVI settings");
            if(regs['h98]!=3 || regs['h9a]!='he0 || regs['h9c]!='h30 || regs['h9d]!='h61 ||
               regs['ha2]!='ha4 || regs['ha3]!='ha4 || regs['he0]!='hd0 || regs['hf9]!=0)
                $fatal(1,"required fixed register mismatch");
            if({regs['h18],regs['h19],regs['h1a],regs['h1b],regs['h1c],regs['h1d],regs['h1e],regs['h1f]}
               !==64'he66904ac00001c81) $fatal(1,"CSC red row differs from Table59");
            if({regs['h20],regs['h21],regs['h22],regs['h23],regs['h24],regs['h25],regs['h26],regs['h27]}
               !==64'h1cbc04ad1e6e0220) $fatal(1,"CSC green row differs from Table59");
            if({regs['h28],regs['h29],regs['h2a],regs['h2b],regs['h2c],regs['h2d],regs['h2e],regs['h2f]}
               !==64'h1ffe04ad081a1ba9) $fatal(1,"CSC blue row differs from Table59");
            if(regs['h17]!=(VIDEO_720P ? 2 : 0)) $fatal(1,"input aspect/sync mismatch");
            if(regs['h4a]!='h80 || regs['hba]!='h60) $fatal(1,"update mode/clock wrong");
            if(regs['ha1]!=0 || regs['h4b]!='h80 || regs['h40]!='h80)
                $fatal(1,"TMDS or AVMUTE state not restored");
        end
    endtask
    integer before_count, before_naks;
    initial begin
        for(i=0;i<256;i=i+1) regs[i]=0;
        regs['h96]='h80;
        regs['ha1]='h3c; regs['h4b]='h40; // previous bitstream's power/mute state
        hpd=0; reboot(); #2000000;
        if(configured || error || writes!=0) $fatal(1,"must wait for monitor before writing ADV registers");
        hpd=1; wait_configured(); check_registers();
        if(mux_writes!=1 || writes!=68) $fatal(1,"unexpected initial transaction count %0d/%0d",mux_writes,writes);
        $display("PASS startup: correct mux, addresses, 67 configuration writes, repeated-START reads, final NACK");

        // A complete unplug leaves the controller idle without declaring an error.
        hpd=0; regs['h96]='h80;
        #2000000;
        if(configured || error) $fatal(1,"unplug did not clear configured");
        before_count=configure_count;
        #2000000;
        if(configure_count!=before_count) $fatal(1,"configured registers while HPD low");
        hpd=1; regs['h96]='h80;
        wait_configured(); check_registers();
        if(configure_count!=before_count+1) $fatal(1,"replug did not reinitialize");
        $display("PASS unplug/replug");

        // Sticky HPD catches a reset pulse shorter than the polling interval.
        before_count=configure_count; regs['h96]='h80; regs['h16]=0;
        wait(!configured); wait_configured(); check_registers();
        if(configure_count!=before_count+1) $fatal(1,"missed sticky HPD event");
        $display("PASS short HPD pulse recovery");

        reboot(); wait(configure_count>before_count+1); hpd=0; regs['h96]='h80;
        #22000000;
        if(configured || error) $fatal(1,"HPD removal during programming was not detected");
        hpd=1; wait_configured(); check_registers();
        $display("PASS HPD removal during initialization");

        // Each position of a three-byte write can NACK; retry entire transaction.
        for(i=0;i<3;i=i+1) begin
            nak_byte=i; inject_naks=1; before_naks=observed_naks;
            reboot(); wait_configured(); check_registers();
            if(observed_naks!=before_naks+1) $fatal(1,"NACK injection not exercised");
        end
        $display("PASS address/register/data NACK retry");

        persistent_nak=1; before_naks=observed_naks; reboot(); wait(error);
        if(observed_naks!=before_naks+3 || configured) $fatal(1,"retry bound incorrect");
        before_count=starts; #2000000;
        if(starts!=before_count || scl!==1 || sda!==1) $fatal(1,"error must latch and release bus");
        persistent_nak=0;
        reboot(); wait_configured();
        $display("PASS bounded NACK error, released bus, reset recovery");

        // Reset in the middle of an active transfer must not strand the bus.
        wait(scl===0); reboot(); wait_configured(); check_registers();
        $display("PASS mid-transaction reset");

        // Stretch for longer than one bit, but below the configured timeout.
        reboot(); wait(scl===0); slave_scl_low=1; #50000; slave_scl_low=0;
        wait_configured(); check_registers();
        $display("PASS clock stretching");

        // Slave holding SDA after interrupted read: nine recovery clocks + STOP.
        reboot(); suppress_model=1; stuck_sda=1;
        repeat(9) @(posedge scl);
        @(negedge scl); stuck_sda=0; suppress_model=0; mode=WAIT_STOP;
        last_rise=0; last_fall=0;
        wait_configured(); check_registers();
        $display("PASS nine-clock SDA recovery");

        reboot(); suppress_model=1; stuck_sda=1; wait(error);
        if(configured) $fatal(1,"stuck SDA reported configured");
        stuck_sda=0; suppress_model=0; mode=WAIT_STOP;
        last_rise=0; last_fall=0;
        reboot(); wait_configured();
        $display("PASS permanently stuck SDA bounded error");

        reboot(); slave_scl_low=1; wait(error);
        if(configured) $fatal(1,"stuck SCL reported configured");
        slave_scl_low=0; reboot(); wait_configured();
        $display("PASS stuck SCL timeout and reset recovery");

        // A powered but unlocked transmitter is not declared configured.
        pll=0; reboot(); wait(error);
        if(configured) $fatal(1,"unlocked PLL reported configured");
        pll=1; reboot(); wait_configured();
        $display("PASS bounded PLL-lock failure and recovery");
        $display("PASS test_init: %0d writes, %0d reads, %0d starts",writes,read_count,starts);
        $finish;
    end
    initial begin #600000000; $fatal(1,"test timeout"); end
endmodule
