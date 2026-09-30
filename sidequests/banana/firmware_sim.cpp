#include "Vvexriscv_tpu_soc.h"
#include "banana_fixture.h"
#include <cstdint>
#include <iostream>

int main() {
    Vvexriscv_tpu_soc dut;
    dut.uart_rx = 1;
    dut.ext_req_ready = 1;
    dut.ext_resp_valid = 0;
    dut.ext_resp_rdata = 0;
    dut.ext_resp_error = 1;
    unsigned checked = 0;
    for (unsigned cycle = 0; cycle < 20000000; ++cycle) {
        dut.clk = 0;
        dut.rst = cycle < 8;
        dut.ready_to_run = cycle > 20;
        dut.eval();
        dut.clk = 1;
        dut.eval();
        if (dut.fault || dut.ext_req_valid) {
            std::cerr << "FAULT or external memory access\n";
            return 1;
        }
        if (dut.report_valid) {
            if (checked >= 96 || dut.report_data != uint32_t(banana_expected[checked])) {
                std::cerr << "Banana transform mismatch at " << checked << '\n';
                return 2;
            }
            ++checked;
        }
        if (dut.exit_valid) {
            std::cout << "banana firmware: exit=" << dut.exit_code
                      << " checked=" << checked << " cycles_to_exit=" << cycle
                      << " external_memory_accesses=0\n";
            return dut.exit_code || checked != 96 ? 3 : 0;
        }
    }
    std::cerr << "TIMEOUT at PC " << std::hex << dut.pc_debug
              << std::dec << " checked=" << checked << '\n';
    return 4;
}
