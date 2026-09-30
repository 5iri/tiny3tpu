#include "Vvexriscv_tpu_soc.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>

// Functional RTL simulation. Frequency sets the external UART receiver's
// sampling interval; this does not model FPGA propagation delays or the PLL.
int main(int argc, char **argv) {
    const double hz = argc > 1 ? std::strtod(argv[1], nullptr) : 100000000;
    const double bit_cycles = hz / 115200.0;
    Vvexriscv_tpu_soc dut;
    dut.uart_rx = 1;
    dut.ext_req_ready = 1;
    dut.ext_resp_valid = 0;
    dut.ext_resp_rdata = 0;
    dut.ext_resp_error = 1;
    unsigned results = 0, errors = 0, exit_cycle = 0, exit_code = 0;
    int rx_bit = -1;
    unsigned rx_byte = 0;
    double sample = 0;
    std::string uart;
    for (unsigned cycle = 0; cycle < 20000000; ++cycle) {
        dut.clk = 0;
        dut.rst = cycle < 8;
        dut.ready_to_run = cycle > 20;
        dut.eval();
        dut.clk = 1;
        dut.eval();
        if (dut.fault || dut.ext_req_valid) {
            std::cerr << "FAULT at PC " << std::hex << dut.pc_debug << '\n';
            return 2;
        }
        if (rx_bit < 0 && !dut.uart_tx) {
            rx_bit = 0; rx_byte = 0;
            sample = cycle + 1.5 * bit_cycles;
        } else if (rx_bit >= 0 && cycle >= std::lround(sample)) {
            if (rx_bit < 8) {
                rx_byte |= unsigned(dut.uart_tx) << rx_bit++;
                sample += bit_cycles;
            } else {
                if (!dut.uart_tx) ++errors;
                uart += char(rx_byte);
                rx_bit = -1;
            }
        }
        if (dut.report_valid) {
            if (results >= 35) return 3;
            int32_t expected = 0;
            for (unsigned k = 0; k < 11; ++k)
                expected += (int(((results / 7) * 11 + k) % 17) - 8)
                          * (int((k * 7 + results % 7) % 13) - 6);
            if (dut.report_data != uint32_t(expected)) return 4;
            ++results;
        }
        if (dut.exit_valid && !exit_cycle) {
            exit_cycle = cycle; exit_code = dut.exit_code;
        }
        if (exit_cycle && cycle > exit_cycle + 100000) {
            std::cout << "receiver_clock_hz=" << uint64_t(hz)
                      << " exit=" << exit_code << " checked_results=" << results
                      << " exit_cycle=" << exit_cycle << " uart_framing_errors=" << errors
                      << " uart_selftest_pass=" << (uart.find("SELFTEST PASS") != std::string::npos)
                      << "\nuart=";
            for (unsigned char c : uart) {
                if ((c >= 32 && c <= 126) || c == '\n') std::cout << c;
                else std::cout << "\\x" << std::hex << std::setw(2) << std::setfill('0') << unsigned(c) << std::dec;
            }
            std::cout << '\n';
            return exit_code || results != 35 || errors || uart.find("SELFTEST PASS") == std::string::npos ? 5 : 0;
        }
    }
    std::cerr << "TIMEOUT\n";
    return 6;
}
