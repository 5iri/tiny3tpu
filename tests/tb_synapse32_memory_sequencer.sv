`timescale 1ns/1ps
`default_nettype none

module tb_synapse32_memory_sequencer;
    localparam logic [31:0] RESET_PC = 32'h0000_1000;
    localparam logic [31:0] ERROR_ADDR = 32'hdead_0000;
    localparam integer NOPS = 14;
    localparam integer DATAOPS = 13;

    logic clk = 1'b0;
    logic rst = 1'b1;
    logic ready_to_run = 1'b0;

    logic [31:0] cpu_pc = RESET_PC;
    logic cpu_rd_en = 1'b0;
    logic cpu_wr_en = 1'b0;
    logic [31:0] cpu_rd_addr = 32'b0;
    logic [31:0] cpu_wr_addr = 32'b0;
    logic [31:0] cpu_wdata = 32'b0;
    logic [3:0] cpu_wstrb = 4'b0;
    logic [2:0] cpu_load_type = 3'b0;
    wire [31:0] cpu_instr;
    wire [31:0] cpu_rdata;
    wire cpu_step;
    wire fault;

    wire req_valid;
    wire req_ready;
    wire req_write;
    wire [31:0] req_addr;
    wire [31:0] req_wdata;
    wire [3:0] req_wstrb;
    logic resp_valid;
    wire resp_ready;
    logic [31:0] resp_rdata;
    logic resp_error;

    synapse32_memory_sequencer #(.RESET_PC(RESET_PC)) dut (
        .clk(clk), .rst(rst), .ready_to_run(ready_to_run),
        .cpu_pc(cpu_pc), .cpu_rd_en(cpu_rd_en), .cpu_wr_en(cpu_wr_en),
        .cpu_rd_addr(cpu_rd_addr), .cpu_wr_addr(cpu_wr_addr),
        .cpu_wdata(cpu_wdata), .cpu_wstrb(cpu_wstrb),
        .cpu_load_type(cpu_load_type), .cpu_instr(cpu_instr),
        .cpu_rdata(cpu_rdata), .cpu_step(cpu_step), .fault(fault),
        .req_valid(req_valid), .req_ready(req_ready),
        .req_write(req_write), .req_addr(req_addr),
        .req_wdata(req_wdata), .req_wstrb(req_wstrb),
        .resp_valid(resp_valid), .resp_ready(resp_ready),
        .resp_rdata(resp_rdata), .resp_error(resp_error)
    );

    always #5 clk = ~clk;

    integer errors = 0;
    integer phase = 1;
    integer cycle_count = 0;
    integer fetch_count = 0;
    integer data_count = 0;
    integer op_index = 0;
    integer active_ops = NOPS;
    integer step_count = 0;
    integer steps_before_error = 0;
    integer settle_wait_count = 0;

    logic [2:0] op_kind [0:NOPS-1]; // 0=no-op, 1=store, 2=load
    logic [31:0] op_addr [0:NOPS-1];
    logic [31:0] op_wdata [0:NOPS-1];
    logic [3:0] op_strobe [0:NOPS-1];
    logic [2:0] op_load [0:NOPS-1];
    logic [31:0] op_next_pc [0:NOPS-1];
    logic [31:0] op_expected [0:NOPS-1];

    logic [31:0] expected_data_addr [0:DATAOPS-1];
    logic expected_data_write [0:DATAOPS-1];
    logic [31:0] expected_data_wdata [0:DATAOPS-1];
    logic [3:0] expected_data_wstrb [0:DATAOPS-1];

    logic [31:0] mem3000 = 32'b0;
    logic [31:0] mem3004 = 32'b0;
    logic [31:0] mem3008 = 32'b0;

    logic pending = 1'b0;
    integer pending_delay = 0;
    logic pending_write = 1'b0;
    logic [31:0] pending_addr = 32'b0;
    logic [31:0] pending_wdata = 32'b0;
    logic [3:0] pending_wstrb = 4'b0;

    // Deliberate request-channel backpressure.  A request is accepted only
    // when the responder is idle and this repeating pattern says ready.
    assign req_ready = !pending && !resp_valid && ((cycle_count % 4) != 0);

    task automatic fail(input string message);
        begin
            errors = errors + 1;
            $display("FAIL: %s at t=%0t", message, $time);
        end
    endtask

    function automatic [31:0] memory_read(input [31:0] address);
        begin
            case (address)
                32'h0000_3000: memory_read = mem3000;
                32'h0000_3004: memory_read = mem3004;
                32'h0000_3008: memory_read = mem3008;
                default: memory_read = 32'h0000_0013 ^ address;
            endcase
        end
    endfunction

    task automatic check_request;
        integer i;
        begin
            if (req_addr[1:0] != 2'b00)
                fail("bus request was not word aligned");
            if (phase == 1) begin
                if (req_addr >= 32'h0000_3000) begin
                    if (data_count >= DATAOPS) begin
                        fail("extra data request after all expected requests");
                    end else begin
                        if (req_addr !== expected_data_addr[data_count])
                            fail("data request address mismatch");
                        if (req_write !== expected_data_write[data_count])
                            fail("data request direction mismatch");
                        if (req_wdata !== expected_data_wdata[data_count])
                            fail("shifted store data mismatch");
                        if (req_wstrb !== expected_data_wstrb[data_count])
                            fail("shifted store strobe mismatch");
                        data_count = data_count + 1;
                    end
                end else begin
                    if (fetch_count == 0) begin
                        if (req_addr !== RESET_PC)
                            fail("boot fetch address mismatch");
                    end else if (fetch_count - 1 < NOPS) begin
                        if (req_addr !== op_next_pc[fetch_count - 1])
                            fail("repeated or next fetch PC mismatch");
                    end
                    fetch_count = fetch_count + 1;
                end
            end else if (phase == 2) begin
                if (req_addr == ERROR_ADDR) begin
                    if (!req_write)
                        data_count = data_count + 1;
                    else
                        fail("error test was unexpectedly a write");
                end else if (fetch_count == 0 && req_addr == RESET_PC) begin
                    fetch_count = fetch_count + 1;
                end else begin
                    fail("unexpected request during bus-error test");
                end
            end
            // Keep an explicit reference to i so older Icarus versions accept
            // this task's local declaration consistently.
            i = 0;
        end
    endtask

    // Behavioral memory target: delayed responses, stable response payload
    // while valid is held, and a sticky error for ERROR_ADDR.
    always @(posedge clk) begin
        if (rst) begin
            cycle_count <= 0;
            fetch_count <= 0;
            data_count <= 0;
            pending <= 1'b0;
            pending_delay <= 0;
            resp_valid <= 1'b0;
            resp_rdata <= 32'b0;
            resp_error <= 1'b0;
        end else begin
            cycle_count <= cycle_count + 1;

            if (resp_valid && resp_ready) begin
                resp_valid <= 1'b0;
                resp_error <= 1'b0;
            end

            if (pending) begin
                if (pending_delay == 0) begin
                    pending <= 1'b0;
                    resp_valid <= 1'b1;
                    resp_rdata <= pending_write ? 32'b0 : memory_read(pending_addr);
                    resp_error <= (pending_addr == ERROR_ADDR);
                end else begin
                    pending_delay <= pending_delay - 1;
                end
            end else if (!resp_valid && req_valid && req_ready) begin
                check_request();
                pending <= 1'b1;
                pending_delay <= (cycle_count % 3) + 1;
                pending_write <= req_write;
                pending_addr <= req_addr;
                pending_wdata <= req_wdata;
                pending_wstrb <= req_wstrb;

                if (phase == 1 && req_write) begin
                    case (req_addr)
                        32'h0000_3000: begin
                            if (req_wstrb[0]) mem3000[7:0] <= req_wdata[7:0];
                            if (req_wstrb[1]) mem3000[15:8] <= req_wdata[15:8];
                            if (req_wstrb[2]) mem3000[23:16] <= req_wdata[23:16];
                            if (req_wstrb[3]) mem3000[31:24] <= req_wdata[31:24];
                        end
                        32'h0000_3004: begin
                            if (req_wstrb[0]) mem3004[7:0] <= req_wdata[7:0];
                            if (req_wstrb[1]) mem3004[15:8] <= req_wdata[15:8];
                            if (req_wstrb[2]) mem3004[23:16] <= req_wdata[23:16];
                            if (req_wstrb[3]) mem3004[31:24] <= req_wdata[31:24];
                        end
                        32'h0000_3008: begin
                            if (req_wstrb[0]) mem3008[7:0] <= req_wdata[7:0];
                            if (req_wstrb[1]) mem3008[15:8] <= req_wdata[15:8];
                            if (req_wstrb[2]) mem3008[23:16] <= req_wdata[23:16];
                            if (req_wstrb[3]) mem3008[31:24] <= req_wdata[31:24];
                        end
                        default: fail("unexpected valid store address");
                    endcase
                end
            end
        end
    end

    logic held_request = 1'b0;
    logic held_write;
    logic [31:0] held_addr, held_wdata;
    logic [3:0] held_wstrb;
    always @(posedge clk) begin
        if (rst) begin
            held_request <= 1'b0;
        end else if (req_valid && !req_ready) begin
            if (!held_request) begin
                held_request <= 1'b1;
                held_write <= req_write;
                held_addr <= req_addr;
                held_wdata <= req_wdata;
                held_wstrb <= req_wstrb;
            end else begin
                if (req_write !== held_write || req_addr !== held_addr ||
                    req_wdata !== held_wdata || req_wstrb !== held_wstrb)
                    fail("request payload changed under backpressure");
            end
        end else begin
            held_request <= 1'b0;
        end
    end

    // Model the board's BUFGCE simulation contract.  This deliberately keeps
    // CE after a falling-edge sample, even if ready_to_run drops afterward.
    // The late-drop test below must observe the already-armed CPU edge; a low
    // cpu_step at the following system edge is not proof that the CPU did not
    // retire.  ready_to_run represents PLL/run readiness here, not DDR
    // calibration; the physical top currently supplies locked && !rst.
    logic cpu_ce_enabled = 1'b0;
    wire modeled_cpu_clk = clk && cpu_ce_enabled;
    integer modeled_cpu_rises = 0;
    always @(negedge clk) begin
        cpu_ce_enabled <= rst || cpu_step;
    end
    always @(posedge modeled_cpu_clk) begin
        if (!rst)
            modeled_cpu_rises = modeled_cpu_rises + 1;
    end

    // Behavioral CPU: its outputs are changed only at a cpu_step edge and
    // then held throughout the sequencer's potentially long bus transaction.
    always @(posedge clk) begin
        if (rst) begin
            cpu_pc <= RESET_PC;
            cpu_rd_en <= 1'b0;
            cpu_wr_en <= 1'b0;
            cpu_rd_addr <= 32'b0;
            cpu_wr_addr <= 32'b0;
            cpu_wdata <= 32'b0;
            cpu_wstrb <= 4'b0;
            cpu_load_type <= 3'b0;
            op_index <= 0;
            step_count <= 0;
        end else if (cpu_step) begin
            if (phase == 1 && op_index > 0 && op_kind[op_index - 1] == 2 &&
                cpu_rdata !== op_expected[op_index - 1])
                fail("load lane result mismatch");

            step_count = step_count + 1;
            if (op_index < active_ops) begin
                cpu_pc <= op_next_pc[op_index];
                cpu_rd_en <= (op_kind[op_index] == 2);
                cpu_wr_en <= (op_kind[op_index] == 1);
                cpu_rd_addr <= op_addr[op_index];
                cpu_wr_addr <= op_addr[op_index];
                cpu_wdata <= op_wdata[op_index];
                cpu_wstrb <= op_strobe[op_index];
                cpu_load_type <= op_load[op_index];
                op_index <= op_index + 1;
            end else begin
                cpu_pc <= (active_ops == 0) ? RESET_PC : op_next_pc[active_ops - 1];
                cpu_rd_en <= 1'b0;
                cpu_wr_en <= 1'b0;
                cpu_rd_addr <= 32'b0;
                cpu_wr_addr <= 32'b0;
                cpu_wdata <= 32'b0;
                cpu_wstrb <= 4'b0;
                cpu_load_type <= 3'b0;
            end
        end
    end

    task automatic init_valid_program;
        integer i;
        begin
            for (i = 0; i < NOPS; i = i + 1) begin
                op_kind[i] = 0;
                op_addr[i] = 0;
                op_wdata[i] = 0;
                op_strobe[i] = 0;
                op_load[i] = 0;
                op_next_pc[i] = 32'h0000_1000 + (i + 1) * 4;
                op_expected[i] = 0;
            end
            op_kind[0]=1; op_addr[0]=32'h3000; op_wdata[0]=32'h000000a1; op_strobe[0]=4'b0001; op_next_pc[0]=32'h1004;
            op_kind[1]=1; op_addr[1]=32'h3000; op_wdata[1]=32'h000000a1; op_strobe[1]=4'b0001; op_next_pc[1]=32'h1004;
            op_kind[2]=1; op_addr[2]=32'h3001; op_wdata[2]=32'h000000b2; op_strobe[2]=4'b0001; op_next_pc[2]=32'h1008;
            op_kind[3]=1; op_addr[3]=32'h3002; op_wdata[3]=32'h000000c3; op_strobe[3]=4'b0001; op_next_pc[3]=32'h100c;
            op_kind[4]=1; op_addr[4]=32'h3003; op_wdata[4]=32'h000000d4; op_strobe[4]=4'b0001; op_next_pc[4]=32'h1010;
            op_kind[5]=1; op_addr[5]=32'h3004; op_wdata[5]=32'h00001122; op_strobe[5]=4'b0011; op_next_pc[5]=32'h1014;
            op_kind[6]=1; op_addr[6]=32'h3008; op_wdata[6]=32'h55667788; op_strobe[6]=4'b1111; op_next_pc[6]=32'h1018;
            op_kind[7]=2; op_addr[7]=32'h3000; op_load[7]=3'b000; op_expected[7]=32'h000000a1; op_next_pc[7]=32'h101c;
            op_kind[8]=2; op_addr[8]=32'h3002; op_load[8]=3'b100; op_expected[8]=32'h000000c3; op_next_pc[8]=32'h1020;
            op_kind[9]=2; op_addr[9]=32'h3004; op_load[9]=3'b001; op_expected[9]=32'h00001122; op_next_pc[9]=32'h1024;
            op_kind[10]=2; op_addr[10]=32'h3004; op_load[10]=3'b101; op_expected[10]=32'h00001122; op_next_pc[10]=32'h1028;
            op_kind[11]=2; op_addr[11]=32'h3008; op_load[11]=3'b010; op_expected[11]=32'h55667788; op_next_pc[11]=32'h102c;
            op_kind[12]=2; op_addr[12]=32'h3003; op_load[12]=3'b000; op_expected[12]=32'h000000d4; op_next_pc[12]=32'h1030;
            op_kind[13]=0; op_next_pc[13]=32'h1034;

            expected_data_addr[0]=32'h3000; expected_data_write[0]=1; expected_data_wdata[0]=32'h000000a1; expected_data_wstrb[0]=4'b0001;
            expected_data_addr[1]=32'h3000; expected_data_write[1]=1; expected_data_wdata[1]=32'h000000a1; expected_data_wstrb[1]=4'b0001;
            expected_data_addr[2]=32'h3000; expected_data_write[2]=1; expected_data_wdata[2]=32'h0000b200; expected_data_wstrb[2]=4'b0010;
            expected_data_addr[3]=32'h3000; expected_data_write[3]=1; expected_data_wdata[3]=32'h00c30000; expected_data_wstrb[3]=4'b0100;
            expected_data_addr[4]=32'h3000; expected_data_write[4]=1; expected_data_wdata[4]=32'hd4000000; expected_data_wstrb[4]=4'b1000;
            expected_data_addr[5]=32'h3004; expected_data_write[5]=1; expected_data_wdata[5]=32'h00001122; expected_data_wstrb[5]=4'b0011;
            expected_data_addr[6]=32'h3008; expected_data_write[6]=1; expected_data_wdata[6]=32'h55667788; expected_data_wstrb[6]=4'b1111;
            expected_data_addr[7]=32'h3000; expected_data_write[7]=0; expected_data_wdata[7]=0; expected_data_wstrb[7]=0;
            expected_data_addr[8]=32'h3000; expected_data_write[8]=0; expected_data_wdata[8]=0; expected_data_wstrb[8]=0;
            expected_data_addr[9]=32'h3004; expected_data_write[9]=0; expected_data_wdata[9]=0; expected_data_wstrb[9]=0;
            expected_data_addr[10]=32'h3004; expected_data_write[10]=0; expected_data_wdata[10]=0; expected_data_wstrb[10]=0;
            expected_data_addr[11]=32'h3008; expected_data_write[11]=0; expected_data_wdata[11]=0; expected_data_wstrb[11]=0;
            expected_data_addr[12]=32'h3000; expected_data_write[12]=0; expected_data_wdata[12]=0; expected_data_wstrb[12]=0;
        end
    endtask

    task automatic tick(input integer count);
        integer j;
        begin
            for (j = 0; j < count; j = j + 1)
                @(posedge clk);
        end
    endtask

    initial begin
        init_valid_program();

        // Reset and PLL/run-readiness gating: no request may escape while not
        // ready.  This is intentionally distinct from DDR PHY calibration.
        tick(3);
        if (req_valid || cpu_step || fault)
            fail("reset did not quiesce or clear outputs");
        rst = 1'b0;
        tick(5);
        if (req_valid || cpu_step)
            fail("sequencer issued before calibration ready");

        ready_to_run = 1'b1;
        while (step_count < NOPS)
            @(posedge clk);
        if (step_count < NOPS)
            fail("valid program did not retire all CPU steps");
        if (mem3000 !== 32'hd4c3b2a1 || mem3004 !== 32'h00001122 ||
            mem3008 !== 32'h55667788)
            fail("store byte/half/word memory image mismatch");

        // Drop run readiness while a fetch request is in flight.  The accepted
        // request is reset-coordinated, and the sequencer must fault.
        while (!(req_valid && req_ready))
            @(posedge clk);
        ready_to_run = 1'b0;
        tick(4);
        if (!fault)
            fail("calibration loss did not become sticky fault");
        if (cpu_step)
            fail("CPU step remained enabled after calibration loss");

        // A synchronous reset clears sticky fault and again waits for ready.
        rst = 1'b1;
        tick(2);
        if (fault || req_valid || cpu_step)
            fail("reset did not clear calibration fault");
        rst = 1'b0;

        // Bus error test after reset.  The error response must halt without a
        // following fetch or CPU retirement.
        phase = 2;
        steps_before_error = step_count;
        active_ops = 1;
        op_kind[0] = 2;
        op_addr[0] = ERROR_ADDR;
        op_load[0] = 3'b010;
        op_next_pc[0] = 32'h1104;
        ready_to_run = 1'b1;
        while (!fault)
            @(posedge clk);
        if (step_count != steps_before_error + 1)
            fail("bus error did not halt after exactly the issuing CPU step");

        rst = 1'b1;
        tick(2);
        if (fault)
            fail("bus error fault was not reset");
        rst = 1'b0;
        ready_to_run = 1'b0;
        tick(3);
        if (req_valid || cpu_step)
            fail("post-error reset issued before ready");
        ready_to_run = 1'b1;
        // Confirm the reset really permits a new boot fetch, then exercise the
        // important BUFGCE boundary: drop ready_to_run after the falling edge
        // that sampled cpu_step.  The sequencer output goes low and faults, but
        // the already-armed modeled CPU clock still has one rising edge.  This
        // prevents any test from incorrectly claiming a no-CPU-retire proof.
        while (!req_valid)
            @(posedge clk);
        while (!cpu_step)
            @(negedge clk);
        begin : late_ready_drop
            integer rises_before_drop;
            rises_before_drop = modeled_cpu_rises;
            ready_to_run = 1'b0;
            @(posedge clk);
            #1;
            if (!fault)
                fail("late ready loss did not fault sequencer");
            if (cpu_step)
                fail("cpu_step remained high after late ready loss");
            if (modeled_cpu_rises != rises_before_drop + 1)
                fail("BUFGCE model did not show the already-armed CPU edge");
            $display("INFO: late ready loss after BUFGCE CE sample permits one armed CPU edge; no no-retire proof");
        end

        if (errors == 0)
            $display("PASS: synapse32_memory_sequencer comprehensive behavioral test");
        else
            $display("FAIL: %0d sequencer test failure(s)", errors);
        $finish;
    end

    initial begin
        repeat (5000) @(posedge clk);
        fail("watchdog timeout");
        $finish;
    end
endmodule
`default_nettype wire
