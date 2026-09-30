`timescale 1ns/1ps
`default_nettype none

module tb_litedram_wishbone_bridge;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst = 1;
    reg req_valid = 0, req_write = 0;
    reg [31:0] req_addr = 0, req_wdata = 0;
    reg [3:0] req_wstrb = 0;
    wire req_ready, resp_valid, resp_error;
    reg resp_ready = 0;
    wire [31:0] resp_rdata;
    wire [29:0] wb_adr;
    wire [31:0] wb_dat_w;
    wire [3:0] wb_sel;
    wire wb_cyc, wb_stb, wb_we;
    reg wb_ack = 0, wb_err = 0;
    reg [31:0] wb_dat_r = 0;
    integer accepted = 0, consumed = 0;

    litedram_wishbone_bridge dut (.*);

    always @(posedge clk) begin
        if (!rst) begin
            if (req_valid && req_ready) accepted = accepted + 1;
            if (resp_valid && resp_ready) consumed = consumed + 1;
        end
    end

    task tick;
        begin @(posedge clk); #1; end
    endtask

    task check_bus;
        input [31:0] address, data;
        input [3:0] mask;
        input write_enable;
        begin
            if ({wb_cyc, wb_stb, req_ready, resp_valid} !== 4'b1100)
                $fatal(1, "Incorrect active-bus handshake");
            if (wb_adr !== address[31:2] || wb_dat_w !== data ||
                wb_sel !== mask || wb_we !== write_enable)
                $fatal(1, "Wishbone payload mismatch addr=%h", address);
        end
    endtask

    task issue;
        input [31:0] address, data;
        input [3:0] mask;
        input write_enable;
        begin
            @(negedge clk);
            if (!req_ready) $fatal(1, "Bridge not idle");
            req_valid = 1;
            req_addr = address; req_wdata = data;
            req_wstrb = mask; req_write = write_enable;
            tick;
            check_bus(address, data, mask, write_enable);
            // Leave valid high to challenge duplicate acceptance, and change
            // payload to a pending next request throughout BUS/RESPONSE.
            @(negedge clk);
            req_addr = ~address; req_wdata = ~data;
            req_wstrb = ~mask; req_write = ~write_enable;
        end
    endtask

    task finish_bus;
        input ack, err;
        input [31:0] data;
        integer n, before_accept;
        begin
            before_accept = accepted;
            @(negedge clk);
            wb_ack = ack; wb_err = err; wb_dat_r = data;
            tick;
            if ({wb_cyc, wb_stb, req_ready, resp_valid} !== 4'b0001 ||
                resp_error !== err || resp_rdata !== data)
                $fatal(1, "Completion mismatch ACK=%b ERR=%b", ack, err);
            // Late/held slave termination and changing slave data must not
            // alter the held native response or reissue Wishbone traffic.
            @(negedge clk); wb_ack = 1; wb_err = !err; wb_dat_r = ~data;
            for (n=0; n<5; n=n+1) begin
                tick;
                if ({wb_cyc, wb_stb, req_ready, resp_valid} !== 4'b0001 ||
                    resp_error !== err || resp_rdata !== data || accepted != before_accept)
                    $fatal(1, "Response changed or request duplicated under backpressure");
            end
            @(negedge clk); resp_ready = 1;
            tick;
            if (accepted != before_accept || resp_valid || wb_cyc || !req_ready)
                $fatal(1, "Accepted a request on response-consumption edge");
            @(negedge clk);
            req_valid = 0; resp_ready = 0; wb_ack = 0; wb_err = 0;
            tick;
        end
    endtask

    task reset_bridge;
        begin
            @(negedge clk);
            rst = 1; req_valid = 0; resp_ready = 0;
            // Coordinated slave reset drops pending bus terminations too.
            wb_ack = 0; wb_err = 0;
            tick;
            if (wb_cyc || wb_stb || resp_valid || req_ready || resp_error)
                $fatal(1, "Reset failed to clear transaction state");
            @(negedge clk); rst = 0;
            tick;
            if (!req_ready || resp_valid || wb_cyc) $fatal(1, "Reset recovery failed");
        end
    endtask

    integer i;
    initial begin
        reset_bridge;
        // Unsolicited slave ACK/ERR in IDLE must not create a response.
        @(negedge clk); wb_ack = 1; wb_err = 1;
        tick;
        if (resp_valid || !req_ready) $fatal(1, "Stray termination accepted");
        @(negedge clk); wb_ack = 0; wb_err = 0;

        issue(32'hf000012c, 32'h12345678, 4'hf, 0);
        for (i=0; i<7; i=i+1) begin
            tick;
            check_bus(32'hf000012c, 32'h12345678, 4'hf, 0);
        end
        finish_bus(1, 0, 32'h89abcdef);

        // All masks, including zero; preserve full high address bits and
        // discard only byte offset bits (no base subtraction or lane shift).
        for (i=0; i<16; i=i+1) begin
            issue(32'hc0000100+i, 32'hcafe1234+i, i[3:0], 1);
            tick;
            check_bus(32'hc0000100+i, 32'hcafe1234+i, i[3:0], 1);
            finish_bus(1, 0, 0);
        end
        issue(32'h40000000, 0, 4'hf, 0);
        finish_bus(0, 1, 32'hbad00001);
        issue(32'hfffffffc, 32'hdeadbeef, 4'h5, 1);
        finish_bus(1, 1, 32'hbad00002);
        if (accepted != 19 || consumed != 19)
            $fatal(1, "Transaction counts before reset: %0d/%0d", accepted, consumed);

        issue(32'h40001000, 0, 4'hf, 0);
        tick;
        reset_bridge; // Abort a waiting Wishbone cycle.
        issue(32'hf0000000, 0, 4'hf, 0);
        @(negedge clk); wb_ack = 1; wb_dat_r = 32'h55;
        tick;
        if (!resp_valid) $fatal(1, "Expected held response before reset");
        reset_bridge; // Abort an unconsumed response.

        // Immediate classic termination and an already-ready native consumer.
        @(negedge clk);
        resp_ready = 1; req_valid = 1; req_write = 1;
        req_addr = 32'h40000004; req_wdata = 32'h11223344; req_wstrb = 4'hf;
        tick;
        check_bus(32'h40000004, 32'h11223344, 4'hf, 1);
        @(negedge clk); req_valid = 0; wb_ack = 1; wb_dat_r = 32'hfeedface;
        tick;
        if (!resp_valid || resp_error || resp_rdata !== 32'hfeedface || wb_cyc)
            $fatal(1, "Fast completion failed");
        @(negedge clk); wb_ack = 0;
        tick;
        if (resp_valid || !req_ready || accepted != 22 || consumed != 20)
            $fatal(1, "Final state/count mismatch: %0d/%0d", accepted, consumed);
        $display("PASS: litedram_wishbone_bridge (22 accepted, 20 consumed, 2 reset-aborted)");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "Test timeout");
    end
endmodule

`default_nettype wire
