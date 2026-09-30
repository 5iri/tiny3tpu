`timescale 1ns/1ps
// Exercise the real controller's BIST generator/checker with an abstract memory
// service. Calibration and PHY are deliberately bypassed: this is NOT a DDR3
// electrical/protocol simulation. MICRON_SIM limits BIST to 256 burst counters.
module kc705_uberddr3_bist_tb;
    reg clk = 0, rst_n = 0, active = 0;
    wire done, passed, failed;
    wire [31:0] debug;
    reg stall = 0, ack = 0;
    reg [511:0] data = 0;
    reg [3:0] aux = 0;
    reg [31:0] ack_pipe = 0;
    reg [511:0] data_pipe [0:31];
    reg [3:0] aux_pipe [0:31];
    reg [511:0] storage [0:511];
    reg [63:0] mask_seen = 0;
    integer mode = 0, cycles = 0, writes = 0, reads = 0, masked_writes = 0;
    integer slot, byte_index, i, j, delay = 1;
    wire reply_ack = delay == 1 ? ack : ack_pipe[delay-2];
    wire [511:0] reply_data = delay == 1 ? data : data_pipe[delay-2];
    wire [3:0] reply_aux = delay == 1 ? aux : aux_pipe[delay-2];
    always #5 clk = !clk;
    ddr3_controller #(.CONTROLLER_CLK_PERIOD(10000), .DDR3_CLK_PERIOD(2500),
        .ROW_BITS(14), .COL_BITS(10), .BA_BITS(3), .LANES(8), .AUX_WIDTH(4),
        .SDRAM_CAPACITY(2), .SPEED_BIN(0), .TRCD(15000), .TRP(15000), .TRAS(37500),
        .MICRON_SIM(1), .ODELAY_SUPPORTED(1), .SECOND_WISHBONE(0),
        .BIST_MODE(1), .BIST_TEST_DATAMASK(1), .ECC_ENABLE(0), .WB_ERROR(0),
        .DIC(2'b01), .RTT_NOM(3'b001), .DUAL_RANK_DIMM(0), .DLL_OFF(0)
    ) dut (
        .i_controller_clk(clk), .i_rst_n(rst_n),
        .i_wb_cyc(1'b1), .i_wb_stb(1'b0), .i_wb_we(1'b0),
        .i_wb_addr(24'b0), .i_wb_data(512'b0), .i_wb_sel(64'hffffffffffffffff), .i_aux(4'b0),
        .i_wb2_cyc(1'b0), .i_wb2_stb(1'b0), .i_wb2_we(1'b0),
        .i_wb2_addr(7'b0), .i_wb2_data(32'b0), .i_wb2_sel(4'b0),
        .i_phy_iserdes_data(512'b0), .i_phy_iserdes_dqs(64'b0),
        .i_phy_iserdes_bitslip_reference(64'b0), .i_phy_idelayctrl_rdy(1'b1),
        .i_user_self_refresh(1'b0), .o_calib_complete(done), .o_debug1(debug)
    );
    kc705_uberddr3_status #(.TIMER_BITS(18)) status (.clk(clk), .rst_n(rst_n),
        .done(done), .debug(debug), .passed(passed), .failed(failed));

    always @(negedge clk) begin
        cycles = cycles + 1;
        stall = (cycles % 7 == 3 || cycles % 7 == 4);
    end
    always @(posedge clk) begin
        ack_pipe <= {ack_pipe[30:0], ack};
        data_pipe[0] <= data;
        aux_pipe[0] <= aux;
        for (j = 1; j < 32; j = j + 1) begin
            data_pipe[j] <= data_pipe[j-1];
            aux_pipe[j] <= aux_pipe[j-1];
        end
        ack <= 0;
        if (active && dut.calib_stb && !stall) begin
            // BIST mode 1 uses low addresses, or rotates its row bits into the
            // high address field. Give these disjoint sets separate storage.
            slot = dut.calib_addr < 256 ? dut.calib_addr : 256 + dut.calib_addr[23:10];
            if (slot >= 512) $fatal(1, "unexpected BIST address %h", dut.calib_addr);
            aux <= dut.calib_aux;
            ack <= 1;
            if (dut.calib_we) begin
                writes = writes + 1;
                if (dut.calib_sel != 64'hffffffffffffffff) begin
                    masked_writes = masked_writes + 1;
                    mask_seen = mask_seen | dut.calib_sel;
                end
                for (byte_index = 0; byte_index < 64; byte_index = byte_index + 1)
                    if (dut.calib_sel[byte_index] || mode == 2)
                        storage[slot][8*byte_index +: 8] <= dut.calib_data[8*byte_index +: 8];
            end else begin
                reads = reads + 1;
                data <= storage[slot] ^
                    (((mode == 1 && reads == 1) || (mode == 3 && reads == 256)) ? 512'b1 :
                     (mode >= 4 && reads == 1) ? (512'b1 << ((mode-4)*64+63)) : 512'b0);
            end
        end
    end
    initial begin
        if (!$value$plusargs("mode=%d", mode)) mode = 0;
        if (!$value$plusargs("delay=%d", delay)) delay = 1;
        if (!$value$plusargs("offset=%d", cycles)) cycles = 0;
        for (i = 0; i < 512; i = i + 1) storage[i] = 0;
        // Substitute only the BIST's memory service; keep the real FSM,
        // data generation, mask sequencing, checker and retry behavior.
        force dut.o_wb_stall_calib = stall;
        force dut.o_wb_ack_uncalibrated = reply_ack;
        force dut.o_wb_data = reply_data;
        force dut.o_aux = reply_aux;
        repeat (8) @(negedge clk);
        rst_n = 1;
        repeat (8) @(negedge clk);
        force dut.state_calibrate = 17;
        force dut.initial_calibration_done = 1;
        @(negedge clk);
        release dut.state_calibrate;
        active = 1;
        wait (passed || failed);
        #1;
        if (mode == 0) begin
            if (!passed || failed || dut.wrong_read_data != 0 || dut.correct_read_data != 256)
                $fatal(1, "BIST failed: correct=%d wrong=%d", dut.correct_read_data, dut.wrong_read_data);
            if (reads != 256 || writes != 4288 || masked_writes != 4096 || mask_seen != 64'hffffffffffffffff)
                $fatal(1, "BIST coverage: reads=%d writes=%d masked=%d", reads, writes, masked_writes);
        end else if (!failed || passed || dut.wrong_read_data == 0)
            $fatal(1, "injected memory error was missed");
        $display("PASS: BIST mode=%0d delay=%0d reads=%0d writes=%0d masked=%0d", mode, delay, reads, writes, masked_writes);
        $finish;
    end
    initial begin
        #1000000;
        $fatal(1, "BIST simulation timeout state=%0d correct=%0d wrong=%0d",
               dut.state_calibrate, dut.correct_read_data, dut.wrong_read_data);
    end
endmodule
