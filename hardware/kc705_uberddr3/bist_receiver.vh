// SPDX-License-Identifier: GPL-3.0-or-later
// KC705 adaptation of UberDDR3's calibration-test receiver.
// Compare one byte per register, then reduce the registered results.
// The expected address advances when the response arrives, preserving ordering
// for back-to-back responses. Counts and error notification lag by one cycle.
    localparam KC705_BIST_CHUNKS = wb_data_bits / 8;
    wire kc705_bist_accept = !final_calibration_done &&
                            o_aux[2:0] == 3'd3 && o_wb_ack_uncalibrated;
    reg kc705_bist_valid = 0;
    reg [KC705_BIST_CHUNKS-1:0] kc705_bist_match = 0;
    reg [wb_data_bits-1:0] kc705_bist_data = 0, kc705_bist_expected = 0;
    always @(posedge i_controller_clk) begin
        if (sync_rst_controller || repeat_test) begin
            kc705_bist_valid <= 0;
        end else begin
            kc705_bist_valid <= kc705_bist_accept;
            if (kc705_bist_accept) begin
                kc705_bist_data <= o_wb_data;
                kc705_bist_expected <= correct_data;
                for (integer chunk = 0; chunk < KC705_BIST_CHUNKS; chunk = chunk + 1)
                    kc705_bist_match[chunk] <=
                        o_wb_data[8*chunk +: 8] == correct_data[8*chunk +: 8];
            end
        end
    end
    always @(posedge i_controller_clk) begin
        if (sync_rst_controller) begin
            check_test_address_counter <= 0;
            // Preserve the upstream counters across internal calibration retries.
            reset_from_test <= 0;
        end else begin
            reset_from_test <= 0;
            if (kc705_bist_accept) begin
                check_test_address_counter <= check_test_address_counter + 1'b1;
                if (check_test_address_counter == {wb_addr_bits_sim{1'b1}})
                    check_test_address_counter <= 0;
            end
            if (kc705_bist_valid) begin
                if (&kc705_bist_match) begin
                    correct_read_data <= correct_read_data + 1'b1;
                end else begin
                    wrong_read_data <= wrong_read_data + 1'b1;
                    wrong_data <= kc705_bist_data;
                    expected_data <= kc705_bist_expected;
                    `ifdef UART_DEBUG
                        state_calibrate_last <= state_calibrate;
                        reset_from_test <= 1'b0;
                    `else
                        reset_from_test <= !final_calibration_done;
                    `endif
                end
            end
            if (repeat_test) begin
                check_test_address_counter <= 0;
                correct_read_data <= 0;
                wrong_read_data <= 0;
            end
        end
    end
