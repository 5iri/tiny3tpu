`timescale 1ns/1ps
module tb_litedram_wishbone32_to512;
    reg clk=0;
    always #5 clk=~clk;
    reg rst=1;
    reg [27:0] s_adr=0;
    reg [31:0] s_dat_w=0;
    wire [31:0] s_dat_r;
    reg [3:0] s_sel=0;
    reg s_cyc=0,s_stb=0,s_we=0;
    wire s_ack,s_err;
    wire [23:0] m_adr;
    wire [511:0] m_dat_w;
    reg [511:0] m_dat_r=0;
    wire [63:0] m_sel;
    wire m_cyc,m_stb,m_we;
    reg m_ack=0,m_err=0;
    litedram_wishbone32_to512 dut (.*);
    reg [511:0] memory[0:63];
    reg [31:0] expected[0:1023];
    integer transfers=0;
    reg [31:0] random_state=32'h68ac1973;
    function [31:0] random32;
        input [31:0] x;
        reg [31:0] y;
        begin
            y=x^(x<<13); y=y^(y>>17); random32=y^(y<<5);
        end
    endfunction

    // Adversarial slave: ACK only after a chosen delay, data valid only at ACK.
    // Compare full addresses, every byte enable and every enabled write byte.
    task access;
        input [27:0] address;
        input write;
        input [3:0] mask;
        input [31:0] data;
        input integer delay_cycles;
        input inject_error;
        input ack_with_error;
        reg [511:0] held_data;
        reg [63:0] wanted_mask;
        integer i,j,index;
        begin
            @(negedge clk);
            s_adr=address; s_we=write; s_sel=mask; s_dat_w=data;
            s_cyc=1; s_stb=1;
            @(negedge clk);
            if (!m_cyc || !m_stb || m_adr!==address[27:4] || m_we!==write)
                $fatal(1,"request translation");
            wanted_mask={60'b0,mask} << (4*address[3:0]);
            if (m_sel!==wanted_mask) $fatal(1,"byte select");
            for (i=0;i<64;i=i+1)
                if (m_sel[i] && m_dat_w[i*8+:8]!==data[(i%4)*8+:8])
                    $fatal(1,"write data lane");
            held_data=m_dat_w;
            // Change upstream payload after capture; the target must stay stable.
            s_adr=~address; s_dat_w=~data; s_sel=~mask; s_we=~write;
            for (j=0;j<delay_cycles;j=j+1) begin
                m_dat_r={16{32'hdeadbeef^j}};
                @(negedge clk);
                if (!m_cyc || !m_stb || m_adr!==address[27:4] || m_we!==write ||
                    m_sel!==wanted_mask || m_dat_w!==held_data || s_ack || s_err)
                    $fatal(1,"request changed under backpressure");
            end
            index=address[9:0];
            if (write && !inject_error) begin
                for (i=0;i<64;i=i+1)
                    if (m_sel[i]) memory[m_adr[5:0]][8*i+:8]=m_dat_w[8*i+:8];
                for (i=0;i<4;i=i+1)
                    if (mask[i]) expected[index][8*i+:8]=data[8*i+:8];
            end
            m_dat_r=memory[m_adr[5:0]];
            m_ack=!inject_error || ack_with_error; m_err=inject_error;
            @(negedge clk);
            m_ack=0; m_err=0; m_dat_r=0;
            if (m_cyc || m_stb || s_err!==inject_error || s_ack!==!inject_error)
                $fatal(1,"response/error priority");
            if (!write && !inject_error && s_dat_r!==expected[index])
                $fatal(1,"read lane %d got %h expected %h",address[3:0],s_dat_r,expected[index]);
            @(negedge clk);
            s_cyc=0; s_stb=0;
            if (s_ack || s_err || m_cyc) $fatal(1,"duplicate response");
            transfers=transfers+1;
        end
    endtask

    integer i, lane;
    initial begin
        for (i=0;i<1024;i=i+1) begin
            expected[i]=32'h93470000^i;
            memory[i/16][32*(i%16)+:32]=expected[i];
        end
        repeat(3) @(negedge clk);
        rst=0;
        // All 16 words, every possible byte mask, and read preservation.
        for (lane=0;lane<16;lane=lane+1)
            for (i=0;i<16;i=i+1) begin
                random_state=random32(random_state);
                access(28'habcdef0+lane,1,i,random_state,(i+lane)%21,0,0);
                access(28'habcdef0+lane,0,15,0,(i*3+lane)%21,0,0);
            end
        for (i=0;i<1024;i=i+1) begin
            random_state=random32(random_state);
            access(random_state[27:0],1,random_state[31:28],random_state^32'h5936ce47,i%19,0,0);
            access(random_state[27:0],0,15,0,i%17,0,0);
        end
        for (i=0;i<1024;i=i+1) access(i,0,15,0,i%3,0,0);
        access(28'hfffffff,0,15,0,13,1,0);
        access(28'h8000020,1,7,32'haaaa5555,3,1,1);
        // Reset while waiting must cancel the outstanding transaction.
        @(negedge clk); s_cyc=1;s_stb=1;
        @(negedge clk); if (!m_cyc) $fatal(1,"missing request"); rst=1;
        @(negedge clk); s_cyc=0;s_stb=0;
        if (m_cyc || s_ack || s_err) $fatal(1,"reset did not cancel");
        rst=0;
        access(0,0,15,0,0,0,0);
        $display("PASS: %0d wide DDR bridge accesses, all lanes/masks, stalls, errors, reset",transfers);
        $finish;
    end
    initial begin #2000000; $fatal(1,"timeout"); end
endmodule
