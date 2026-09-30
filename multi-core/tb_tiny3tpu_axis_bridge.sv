`timescale 1ns/1ps
module tb_tiny3tpu_axis_bridge;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0;
    reg [31:0] in_data=0; reg [3:0] in_keep=15;
    reg in_last=0, in_valid=0; wire in_ready;
    wire [31:0] out_data; wire [3:0] out_keep;
    wire out_last, out_valid; reg out_ready=0;
    wire [7:0] awaddr;
    wire [2:0] awprot;
    wire awvalid;
    reg awready;
    wire [31:0] wdata;
    wire [3:0] wstrb;
    wire wvalid;
    reg wready;
    reg [1:0] bresp;
    reg bvalid;
    wire bready;
    wire [7:0] araddr;
    wire [2:0] arprot;
    wire arvalid;
    reg arready;
    reg [31:0] rdata;
    reg [1:0] rresp;
    reg rvalid;
    wire rready;
    tiny3tpu_axis_bridge dut (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(in_data), .s_axis_tkeep(in_keep),
        .s_axis_tlast(in_last), .s_axis_tvalid(in_valid), .s_axis_tready(in_ready),
        .m_axis_tdata(out_data), .m_axis_tkeep(out_keep),
        .m_axis_tlast(out_last), .m_axis_tvalid(out_valid), .m_axis_tready(out_ready),
        .m_axi_awaddr(awaddr),
        .m_axi_awprot(awprot),
        .m_axi_awvalid(awvalid),
        .m_axi_awready(awready),
        .m_axi_wdata(wdata),
        .m_axi_wstrb(wstrb),
        .m_axi_wvalid(wvalid),
        .m_axi_wready(wready),
        .m_axi_bresp(bresp),
        .m_axi_bvalid(bvalid),
        .m_axi_bready(bready),
        .m_axi_araddr(araddr),
        .m_axi_arprot(arprot),
        .m_axi_arvalid(arvalid),
        .m_axi_arready(arready),
        .m_axi_rdata(rdata),
        .m_axi_rresp(rresp),
        .m_axi_rvalid(rvalid),
        .m_axi_rready(rready)
    );
    integer writes=0, reads=0, responses=0;
    integer write_beats=0, b_accepts=0, r_accepts=0, input_beats=0, output_beats=0;
    integer input_stalls=0, reset_cases=0;
    reg prev_out_stall=0, prev_aw_stall=0, prev_w_stall=0, prev_ar_stall=0;
    reg [31:0] saved_out, saved_w;
    reg saved_last;
    reg [3:0] saved_strb;
    reg [7:0] saved_aw, saved_ar;
    always @(posedge clk) begin
        if (!rst_n) begin
            prev_out_stall<=0; prev_aw_stall<=0; prev_w_stall<=0; prev_ar_stall<=0;
        end else begin
            if (prev_out_stall && (!out_valid || out_data!==saved_out || out_last!==saved_last || out_keep!==15))
                $fatal(1,"stream changed under backpressure");
            if (prev_aw_stall && (!awvalid || awaddr!==saved_aw)) $fatal(1,"AW unstable");
            if (prev_w_stall && (!wvalid || wdata!==saved_w || wstrb!==saved_strb)) $fatal(1,"W unstable");
            if (prev_ar_stall && (!arvalid || araddr!==saved_ar)) $fatal(1,"AR unstable");
            prev_out_stall<=out_valid && !out_ready; saved_out<=out_data; saved_last<=out_last;
            prev_aw_stall<=awvalid && !awready; saved_aw<=awaddr;
            prev_w_stall<=wvalid && !wready; saved_w<=wdata; saved_strb<=wstrb;
            prev_ar_stall<=arvalid && !arready; saved_ar<=araddr;
            if (awvalid && awready) writes<=writes+1;
            if (arvalid && arready) reads<=reads+1;
            if (wvalid && wready) write_beats<=write_beats+1;
            if (bvalid && bready) b_accepts<=b_accepts+1;
            if (rvalid && rready) r_accepts<=r_accepts+1;
            if (in_valid && in_ready) input_beats<=input_beats+1;
            if (in_valid && !in_ready) input_stalls<=input_stalls+1;
            if (out_valid && out_ready) output_beats<=output_beats+1;
            if ((awvalid && awprot!==0) || (arvalid && arprot!==0)) $fatal(1,"bad AXI protection");
            if (out_valid && out_keep!==15) $fatal(1,"bad response keep");
        end
    end
    task send_beat(input [31:0] data, input [3:0] keep, input last);
        begin
            @(negedge clk); in_data=data; in_keep=keep; in_last=last; in_valid=1;
            @(posedge clk); while (!in_ready) @(posedge clk);
            @(negedge clk); in_valid=0;
        end
    endtask
    // Leave VALID asserted; successive calls transfer on consecutive clocks
    // when READY permits, including across a packet boundary.
    task continuous_beat(input [31:0] data, input last);
        begin
            @(negedge clk); in_data=data; in_keep=15; in_last=last; in_valid=1;
            @(posedge clk); while (!in_ready) @(posedge clk);
        end
    endtask

    // Slave with no added address/data delay. Responses are asserted on the
    // first falling edge after the request and held until their handshake.
    task fast_write(input [7:0] address, input [31:0] data, input [3:0] strb);
        begin
            @(negedge clk); awready=1; wready=1;
            @(posedge clk); while (!(awvalid && wvalid)) @(posedge clk);
            if (awaddr!==address || wdata!==data || wstrb!==strb) $fatal(1,"wrong fresh/burst write");
            @(negedge clk); awready=0; wready=0; bvalid=1; bresp=0;
            @(posedge clk); while (!bready) @(posedge clk);
            @(negedge clk); bvalid=0;
        end
    endtask

    task fast_read(input [7:0] address, input [31:0] data);
        begin
            @(negedge clk); arready=1;
            @(posedge clk); while (!arvalid) @(posedge clk);
            if (araddr!==address) $fatal(1,"wrong fresh/burst read");
            @(negedge clk); arready=0; rvalid=1; rresp=0; rdata=data;
            @(posedge clk); while (!rready) @(posedge clk);
            @(negedge clk); rvalid=0;
        end
    endtask

    task fast_response(input [31:0] data);
        begin
            @(negedge clk); out_ready=1;
            @(posedge clk); while (!out_valid) @(posedge clk);
            if (out_data!==0 || out_last || out_keep!==15) $fatal(1,"bad burst code");
            @(posedge clk);
            if (!out_valid || out_data!==data || !out_last || out_keep!==15) $fatal(1,"bad consecutive response data");
            @(negedge clk); out_ready=0; responses=responses+1;
        end
    endtask

    task check_idle;
        begin
            if (!in_ready || awvalid || wvalid || arvalid || bready || rready || out_valid)
                $fatal(1,"ghost transaction or response in idle");
        end
    endtask

    // Real coordinated reset: the downstream slave drops its pending work too.
    // This does not assume that a bridge-only reset can undo a committed write.
    task coordinated_reset;
        integer old_aw, old_w, old_ar, old_b, old_r, old_out;
        begin
            @(negedge clk);
            old_aw=writes; old_w=write_beats; old_ar=reads;
            old_b=b_accepts; old_r=r_accepts; old_out=output_beats;
            rst_n=0; in_valid=0; out_ready=0;
            awready=0; wready=0; arready=0; bvalid=0; rvalid=0;
            repeat(2) begin
                @(negedge clk);
                if (in_ready || out_valid || awvalid || wvalid || arvalid || bready || rready)
                    $fatal(1,"active handshake during reset");
            end
            rst_n=1;
            repeat(3) begin @(negedge clk); check_idle(); end
            if (writes!=old_aw || write_beats!=old_w || reads!=old_ar ||
                b_accepts!=old_b || r_accepts!=old_r || output_beats!=old_out)
                $fatal(1,"reset leaked a handshake");
        end
    endtask

    // Exercise every outstanding AXI phase using public pins, not FSM values.
    // 0 neither write channel accepted, 1 AW only, 2 W only, 3 waiting B,
    // 4 stalled AR, 5 waiting R, 6 stalled response data, 7 malformed drain.
    task reset_phase(input integer phase);
        integer old_aw, old_w, old_ar, old_b, old_r, old_out;
        begin
            old_aw=writes; old_w=write_beats; old_ar=reads;
            old_b=b_accepts; old_r=r_accepts; old_out=output_beats;
            if (phase<4) begin
                send_beat(32'h0000510c,15,0); send_beat(32'hbad0cafe,15,1);
                wait(awvalid && wvalid);
                @(negedge clk);
                awready=(phase==1 || phase==3); wready=(phase==2 || phase==3);
                @(posedge clk); @(negedge clk); awready=0; wready=0;
                repeat(3) @(negedge clk);
                if (awvalid!==(phase==0 || phase==2) ||
                    wvalid!==(phase==0 || phase==1) || bready!==(phase==3))
                    $fatal(1,"did not reach write reset phase %0d",phase);
            end else if (phase<6) begin
                send_beat(32'h14,15,0); send_beat(32'hffffffff,15,1);
                wait(arvalid); @(negedge clk); arready=(phase==5);
                @(posedge clk); @(negedge clk); arready=0;
                repeat(3) @(negedge clk);
                if (arvalid!==(phase==4) || rready!==(phase==5))
                    $fatal(1,"did not reach read reset phase %0d",phase);
            end else if (phase==6) begin
                send_beat(0,15,1); wait(out_valid);
                @(negedge clk); out_ready=1;
                @(posedge clk); @(negedge clk); out_ready=0;
                if (!out_valid || !out_last) $fatal(1,"did not reach response data reset");
                repeat(3) @(negedge clk);
            end else begin
                send_beat(32'hf100,15,0); send_beat(0,15,0);
                repeat(3) @(negedge clk);
                if (!in_ready || out_valid || awvalid || wvalid || arvalid)
                    $fatal(1,"malformed drain issued IO");
            end
            if (writes!=old_aw+(phase==1 || phase==3) ||
                write_beats!=old_w+(phase==2 || phase==3) || reads!=old_ar+(phase==5) ||
                b_accepts!=old_b || r_accepts!=old_r || output_beats!=old_out+(phase==6))
                $fatal(1,"unexpected handshakes before reset phase %0d",phase);
            coordinated_reset();
            // Distinct values and addresses catch retained header/payload and
            // stale aw_done/w_done flags; both directions must work after reset.
            fork
                begin send_beat(32'h00003104,15,0); send_beat(32'h1234abcd,15,1); end
                fast_write(8'h04,32'h1234abcd,4'h3);
                receive_response(0,0);
            join
            fork
                begin send_beat(32'h18,15,0); send_beat(32'hcafefeed,15,1); end
                fast_read(8'h18,32'h98765432);
                receive_response(0,32'h98765432);
            join
            repeat(3) @(negedge clk); check_idle();
            if (writes!=old_aw+(phase==1 || phase==3)+1 ||
                write_beats!=old_w+(phase==2 || phase==3)+1 || reads!=old_ar+(phase==5)+1 ||
                b_accepts!=old_b+1 || r_accepts!=old_r+1 || output_beats!=old_out+(phase==6)+4)
                $fatal(1,"recovery transaction count mismatch phase %0d",phase);
            reset_cases=reset_cases+1;
        end
    endtask

    task stream_gaps_and_burst;
        integer old_aw, old_w, old_ar, old_in, old_out, old_stalls;
        begin
            old_aw=writes; old_w=write_beats; old_ar=reads;
            old_in=input_beats; old_out=output_beats; old_stalls=input_stalls;
            send_beat(32'h0000f108,15,0);
            // Invalid bus values during a long source bubble must be ignored.
            repeat(9) begin
                @(negedge clk); in_data=32'hffffffff; in_keep=0; in_last=1;
                if (!in_ready || awvalid || wvalid || arvalid || out_valid)
                    $fatal(1,"IO before valid payload");
            end
            fork
                begin send_beat(32'h10203040,15,1); end
                fast_write(8'h08,32'h10203040,15);
                receive_response(0,0);
            join
            // VALID stays high for all four beats. The second header must wait
            // through the entire first transaction and its stalled response.
            fork
                begin
                    continuous_beat(32'h0000010c,0); // zero WSTRB still transacts
                    continuous_beat(32'h55667788,1);
                    continuous_beat(32'h10,0);
                    continuous_beat(32'hffffffff,1); // ignored read payload
                    @(negedge clk); in_valid=0;
                end
                begin
                    fast_write(8'h0c,32'h55667788,0);
                    fast_read(8'h10,32'hdecafbad);
                end
                begin receive_response(0,0); fast_response(32'hdecafbad); end
            join
            repeat(4) @(negedge clk); check_idle();
            if (writes!=old_aw+2 || write_beats!=old_w+2 || reads!=old_ar+1 ||
                input_beats!=old_in+6 || output_beats!=old_out+6 || input_stalls<=old_stalls)
                $fatal(1,"stream gap/burst dropped or duplicated a transfer");
        end
    endtask
    task receive_response(input [1:0] code, input [31:0] data);
        begin
            out_ready=0;
            wait(out_valid);
            repeat(5) @(negedge clk);
            if (out_data!=={30'b0,code} || out_last || out_keep!==15) $fatal(1,"bad response code");
            out_ready=1; @(posedge clk); @(negedge clk); out_ready=0;
            if (!out_valid || !out_last || out_data!==data) $fatal(1,"bad response data");
            repeat(4) @(negedge clk);
            out_ready=1; @(posedge clk); @(negedge clk); out_ready=0;
            responses=responses+1;
        end
    endtask
    task write_command(input integer order);
        begin
            send_beat(32'h0000a108,15,0); send_beat(32'h87654321,15,1);
            wait(awvalid && wvalid);
            if (awaddr!==8 || awprot!==0 || wdata!==32'h87654321 || wstrb!==10) $fatal(1,"bad write");
            repeat(3) @(negedge clk);
            if (order==0) awready=1; else wready=1;
            @(posedge clk); @(negedge clk); awready=0; wready=0;
            repeat(3) @(negedge clk);
            if (order==0) begin
                if (awvalid || !wvalid) $fatal(1,"AW duplicated"); wready=1;
            end else begin
                if (wvalid || !awvalid) $fatal(1,"W duplicated"); awready=1;
            end
            @(posedge clk); @(negedge clk); awready=0; wready=0;
            repeat(3) @(negedge clk);
            bvalid=1; bresp=order==0 ? 0 : 2;
            @(posedge clk); while(!bready) @(posedge clk);
            @(negedge clk); bvalid=0;
            receive_response(order==0 ? 0 : 2,0);
        end
    endtask
    integer before_writes, before_reads, before_write_beats, phase;
    initial begin
        awready=0; wready=0; bresp=0; bvalid=0;
        arready=0; rdata=0; rresp=0; rvalid=0;
        repeat(3) @(negedge clk); rst_n=1;
        write_command(0); write_command(1);
        send_beat(32'h10,15,0); send_beat(0,15,1);
        wait(arvalid); repeat(3) @(negedge clk);
        if (araddr!==16 || arprot!==0) $fatal(1,"bad read addr");
        arready=1; @(posedge clk); @(negedge clk); arready=0;
        repeat(3) @(negedge clk);
        rvalid=1; rresp=3; rdata=32'hdeadbeef;
        @(posedge clk); while(!rready) @(posedge clk);
        @(negedge clk); rvalid=0;
        receive_response(3,32'hdeadbeef);
        before_writes=writes; before_reads=reads; before_write_beats=write_beats;
        // Short, reserved-bit, sparse-keep, and overlong malformed packets.
        send_beat(32'hf100,15,1); receive_response(2,0);
        send_beat(32'h10000,15,0); send_beat(0,15,1); receive_response(2,0);
        send_beat(32'h200,15,0); send_beat(0,15,1); receive_response(2,0);
        send_beat(0,7,0); send_beat(0,15,1); receive_response(2,0);
        send_beat(0,15,0); send_beat(0,7,1); receive_response(2,0);
        send_beat(0,15,0); send_beat(0,15,0); send_beat(0,15,1); receive_response(2,0);
        if (writes!=before_writes || reads!=before_reads || write_beats!=before_write_beats) $fatal(1,"malformed packet caused IO");
        // Reset discards an unfinished packet and a stalled response.
        send_beat(32'hf100,15,0);
        @(negedge clk); rst_n=0; @(negedge clk); rst_n=1;
        send_beat(0,15,1);
        wait(out_valid); @(negedge clk); rst_n=0; @(negedge clk);
        if (out_valid || awvalid || wvalid || arvalid || in_ready) $fatal(1,"reset did not quiesce");
        rst_n=1; send_beat(0,15,1); receive_response(2,0);
        for (phase=0; phase<8; phase=phase+1) reset_phase(phase);
        stream_gaps_and_burst();
        $display("PASS tiny3tpu_axis_bridge: %0d responses, %0d active-phase resets, %0d input-stall cycles, independent AW/W stalls, malformed packets, stream gaps and back-to-back beats",responses,reset_cases,input_stalls);
        $finish;
    end
    initial begin #100000; $fatal(1,"timeout"); end
endmodule
