`timescale 1ns/1ps
`default_nettype none

module tb_synapse32_axis_mailbox;
    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg rst_n = 1'b0;
    reg cpu_wr_en = 1'b0, cpu_rd_en = 1'b0;
    reg [4:0] cpu_addr = 0;
    reg [31:0] cpu_wdata = 0;
    reg [3:0] cpu_wstrb = 0;
    wire [31:0] cpu_rdata;
    wire [31:0] m_axis_tdata;
    wire [3:0] m_axis_tkeep;
    wire m_axis_tvalid, m_axis_tready, m_axis_tlast;
    reg [31:0] s_axis_tdata = 0;
    reg [3:0] s_axis_tkeep = 0;
    reg s_axis_tvalid = 1'b0, s_axis_tlast = 1'b0;
    wire s_axis_tready;

    reg m_ready_reg = 1'b0;
    assign m_axis_tready = m_ready_reg;

    synapse32_axis_mailbox dut (
        .clk(clk), .rst_n(rst_n),
        .cpu_wr_en(cpu_wr_en), .cpu_rd_en(cpu_rd_en), .cpu_addr(cpu_addr),
        .cpu_wdata(cpu_wdata), .cpu_wstrb(cpu_wstrb), .cpu_rdata(cpu_rdata),
        .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
        .m_axis_tlast(m_axis_tlast),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
        .s_axis_tlast(s_axis_tlast));

    task cpu_write;
        input [4:0] address;
        input [31:0] value;
        input [3:0] strobe;
        begin
            @(negedge clk);
            cpu_addr = address; cpu_wdata = value; cpu_wstrb = strobe;
            cpu_wr_en = 1'b1;
            @(posedge clk);
            @(negedge clk);
            cpu_wr_en = 1'b0; cpu_wstrb = 0;
        end
    endtask

    task cpu_read;
        input [4:0] address;
        output [31:0] value;
        begin
            @(negedge clk);
            cpu_addr = address; cpu_rd_en = 1'b1;
            #1 value = cpu_rdata;
            @(negedge clk);
            cpu_rd_en = 1'b0;
        end
    endtask

    task response_pair;
        input [1:0] code;
        input [31:0] value;
        input [3:0] first_keep;
        input first_last;
        input [3:0] second_keep;
        input second_last;
        begin
            @(negedge clk);
            s_axis_tdata = {30'b0, code}; s_axis_tkeep = first_keep;
            s_axis_tlast = first_last; s_axis_tvalid = 1'b1;
            while (!s_axis_tready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            s_axis_tdata = value; s_axis_tkeep = second_keep;
            s_axis_tlast = second_last;
            while (!s_axis_tready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            s_axis_tvalid = 1'b0; s_axis_tkeep = 0; s_axis_tlast = 1'b0;
        end
    endtask

    task response_short;
        begin
            @(negedge clk);
            s_axis_tdata = 0; s_axis_tkeep = 4'hf;
            s_axis_tlast = 1'b1; s_axis_tvalid = 1'b1;
            while (!s_axis_tready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            s_axis_tvalid = 1'b0; s_axis_tkeep = 0; s_axis_tlast = 1'b0;
        end
    endtask

    task response_overlong;
        input [31:0] value;
        begin
            @(negedge clk);
            s_axis_tdata = 0; s_axis_tkeep = 4'hf;
            s_axis_tlast = 1'b0; s_axis_tvalid = 1'b1;
            while (!s_axis_tready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            s_axis_tdata = value; s_axis_tkeep = 4'hf;
            s_axis_tlast = 1'b0;
            while (!s_axis_tready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            // The drain beat is not part of the response payload.  It only
            // restores packet alignment before the next command.
            s_axis_tdata = 32'hbad0bad0; s_axis_tkeep = 4'hf;
            s_axis_tlast = 1'b1;
            while (!s_axis_tready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            s_axis_tvalid = 1'b0; s_axis_tkeep = 0; s_axis_tlast = 1'b0;
        end
    endtask

    reg [31:0] observed;
    integer failures;
    reg [31:0] held_data;
    reg held_last;

    initial begin
        failures = 0;
        repeat (2) @(posedge clk);
        rst_n = 1'b1;

        // CPU-side SB/SH and misaligned writes are rejected; CONTROL action
        // bits must not fire through an unsupported strobe.
        cpu_write(5'h08, 32'h1, 4'h1);
        cpu_write(5'h09, 32'h1, 4'hf);
        cpu_read(5'h0c, observed);
        if (observed != 32'h4) begin $display("fail CPU misuse status=%h", observed); failures = failures + 1; end
        cpu_write(5'h08, 32'h4, 4'hf);

        // Header is a write to 0x2c with all four downstream byte lanes.
        cpu_write(5'h00, 32'h0000f12c, 4'hf);
        cpu_write(5'h04, 32'hcafebabe, 4'hf);
        cpu_write(5'h08, 32'h1, 4'hf);

        // Backpressure must not change the saved first beat.
        repeat (2) @(posedge clk);
        if (!m_axis_tvalid || m_axis_tdata != 32'h0000f12c ||
            m_axis_tkeep != 4'hf || m_axis_tlast) begin
            $display("fail first valid data=%h last=%b", m_axis_tdata, m_axis_tlast);
            failures = failures + 1;
        end
        held_data = m_axis_tdata; held_last = m_axis_tlast;
        repeat (3) begin
            @(posedge clk);
            if (!m_axis_tvalid || m_axis_tdata != held_data ||
                m_axis_tlast != held_last) begin
                $display("fail hold data=%h last=%b", m_axis_tdata, m_axis_tlast);
                failures = failures + 1;
            end
        end

        @(negedge clk);
        m_ready_reg = 1'b1;
        @(posedge clk); // Accept header.
        @(negedge clk);
        m_ready_reg = 1'b0;
        #1;
        if (!m_axis_tvalid || m_axis_tdata != 32'hcafebabe ||
            !m_axis_tlast) begin
            $display("fail second valid=%b data=%h last=%b state=%0d ready=%b time=%0t",
                     m_axis_tvalid, m_axis_tdata, m_axis_tlast, dut.state,
                     m_axis_tready, $time);
            failures = failures + 1;
        end

        // Staging can change while busy, but a second submit is rejected.
        cpu_write(5'h00, 32'h00000104, 4'hf);
        cpu_write(5'h04, 32'h11112222, 4'hf);
        cpu_write(5'h08, 32'h1, 4'hf);
        cpu_read(5'h0c, observed);
        if ((observed & 32'h5) != 32'h5) begin
            $display("fail overlap status=%h", observed);
            failures = failures + 1;
        end // busy+misuse

        m_ready_reg = 1'b1;
        @(posedge clk); // Accept original payload.
        response_pair(2'b00, 32'h76543210, 4'hf, 1'b0, 4'hf, 1'b1);
        cpu_read(5'h0c, observed);
        if (observed != 32'h6) begin
            $display("fail ready status=%h", observed);
            failures = failures + 1;
        end // ready+misuse
        cpu_read(5'h10, observed);
        if (observed != 0) begin $display("fail code=%h", observed); failures = failures + 1; end
        cpu_read(5'h14, observed);
        if (observed != 32'h76543210) begin $display("fail data=%h", observed); failures = failures + 1; end
        cpu_write(5'h08, 32'h2, 4'hf);
        cpu_read(5'h0c, observed);
        if (observed != 32'h4) begin $display("fail ack status=%h", observed); failures = failures + 1; end
        cpu_write(5'h08, 32'h4, 4'hf);
        cpu_read(5'h0c, observed);
        if (observed != 0) begin $display("fail clear status=%h", observed); failures = failures + 1; end

        // A short response retires immediately on its early TLAST.
        cpu_write(5'h00, 32'h00000080, 4'hf);
        cpu_write(5'h04, 0, 4'hf);
        cpu_write(5'h08, 1, 4'hf);
        m_ready_reg = 1'b1;
        @(posedge clk); @(posedge clk);
        response_short();
        cpu_read(5'h0c, observed);
        if (observed != 32'h2) begin $display("fail short status=%h", observed); failures = failures + 1; end
        cpu_read(5'h10, observed);
        if (observed != 3) begin $display("fail short code=%h", observed); failures = failures + 1; end
        cpu_write(5'h08, 2, 4'hf);

        // An overlong response drains its tail before publishing DECERR.
        cpu_write(5'h00, 32'h00000080, 4'hf);
        cpu_write(5'h04, 0, 4'hf);
        cpu_write(5'h08, 1, 4'hf);
        m_ready_reg = 1'b1;
        @(posedge clk); @(posedge clk);
        response_overlong(32'hdeadbeef);
        cpu_read(5'h10, observed);
        if (observed != 3) begin $display("fail malformed code=%h", observed); failures = failures + 1; end
        cpu_write(5'h08, 2, 4'hf);

        // Reset drops an in-flight request and any old response state.
        cpu_write(5'h00, 32'h00000120, 4'hf);
        cpu_write(5'h04, 32'h01020304, 4'hf);
        cpu_write(5'h08, 1, 4'hf);
        @(posedge clk);
        rst_n = 1'b0;
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        #1;
        if (m_axis_tvalid) begin $display("fail reset valid"); failures = failures + 1; end
        cpu_read(5'h0c, observed);
        if (observed != 0) begin $display("fail reset status=%h", observed); failures = failures + 1; end

        if (failures != 0) begin
            $display("Synapse32 AXIS mailbox: %0d failures", failures);
            $fatal(1, "Synapse32 AXIS mailbox test failed");
        end
        $display("PASS synapse32_axis_mailbox: backpressure, snapshot, overlap, ACK, framing and reset");
        $finish;
    end
endmodule

`default_nettype wire
