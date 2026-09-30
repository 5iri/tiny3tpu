#include "Vsynapse32_cpu_fixture.h"
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>

int main(int argc, char **argv) {
    if (argc != 2) return 1;
    std::ifstream file(argv[1], std::ios::binary);
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
    if (!file || image.empty() || image.size() > 65536) return 2;
    std::vector<uint8_t> ram(65536, 0xa5); // Startup must initialize BSS.
    std::copy(image.begin(), image.end(), ram.begin());
    constexpr uint32_t base = 0x80000000;
    auto read = [&](uint32_t address) -> uint32_t {
        if (address < base || uint64_t(address) + 3 >= uint64_t(base) + ram.size()) return 0;
        uint32_t value = 0;
        for (unsigned i=0; i<4; ++i) value |= uint32_t(ram[address-base+i]) << (8*i);
        return value;
    };
    Vsynapse32_cpu_fixture dut;
    unsigned submits=0, results=0;
    for (unsigned cycle=0; cycle<20000000; ++cycle) {
        dut.clk=0; dut.rst_n=cycle>=5; dut.eval();
        dut.instr=read(dut.pc); dut.ram_rdata=read(dut.rd_addr); dut.eval();
        // Record writes before the edge; this matches the native CPU port.
        const bool wr = dut.rst_n && dut.wr_en;
        const uint32_t addr=dut.wr_addr, data=dut.wr_data;
        const uint8_t strb=dut.wr_strb;
        dut.clk=1; dut.eval();
        if (wr) {
            if (addr == 0x20002000) {
                if (data || strb!=15 || submits<100 || results!=35) {
                    std::cerr << "CPU firmware failed: code=" << data << " submissions=" << submits << '\n';
                    return 3;
                }
                std::cout << "PASS Synapse32 CPU -> AXIS -> TPU: signed 5x11x7 GEMM, "
                          << submits << " commands, " << cycle << " cycles\n";
                return 0;
            }
            if (addr == 0x20002004) {
                if (results>=35 || strb!=15) return 6;
                const unsigned row=results/7, col=results%7;
                int32_t expected=0;
                for (unsigned inner=0; inner<11; ++inner)
                    expected+=(int((row*11+inner)%17)-8)*(int((inner*7+col)%13)-6);
                if (data!=uint32_t(expected)) {
                    std::cerr << "Host scoreboard mismatch at result " << results << '\n'; return 7;
                }
                ++results;
                continue;
            }
            if (addr==0x20001008 && (data&1)) ++submits;
            if (addr>=base && uint64_t(addr)+3<uint64_t(base)+ram.size()) {
                for (unsigned i=0; i<4; ++i)
                    if (strb&(1U<<i)) ram[addr-base+i]=uint8_t(data>>(8*i));
            } else if (addr<0x20001000 || addr>=0x20001020) {
                std::cerr << "Unexpected CPU write 0x" << std::hex << addr << '\n'; return 4;
            }
        }
    }
    std::cerr << "CPU simulation timed out, PC=0x" << std::hex << dut.pc << '\n';
    return 5;
}
