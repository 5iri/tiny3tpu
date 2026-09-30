#include "Vvexriscv_ddr_wide_test_top.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <unordered_map>

int main() {
    Vvexriscv_ddr_wide_test_top dut;
    std::unordered_map<uint32_t,std::array<uint32_t,16>> memory;
    unsigned reads=0,writes=0,results=0,delay=0;
    bool pending=false;
    uint32_t address=0,rng=0x193075ab;
    uint64_t mask=0;
    bool write=false;
    std::array<uint32_t,16> payload{};
    dut.uart_rx=1;dut.m_ack=0;dut.m_err=0;
    for (unsigned cycle=0;cycle<50000000;++cycle) {
        rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;
        dut.clk=0;dut.rst=cycle<8;dut.ready_to_run=cycle>20;
        if (pending && delay) --delay;
        dut.m_ack=pending && !delay;
        for(unsigned i=0;i<16;++i) dut.m_dat_r[i]=dut.m_ack?memory[address][i]:rng;
        dut.eval();
        if(pending) {
            if(!dut.m_cyc || !dut.m_stb || dut.m_adr!=address || dut.m_we!=write || dut.m_sel!=mask)
                return 2;
            for(unsigned i=0;i<16;++i) if(dut.m_dat_w[i]!=payload[i]) return 3;
        }
        const bool accept=!pending && dut.m_cyc && dut.m_stb;
        const bool complete=dut.m_cyc && dut.m_stb && dut.m_ack;
        if(accept) {
            pending=true;delay=1+rng%23;address=dut.m_adr;
            write=dut.m_we;mask=dut.m_sel;
            for(unsigned i=0;i<16;++i) payload[i]=dut.m_dat_w[i];
        }
        if(complete) {
            if(write) {
                for(unsigned i=0;i<64;++i) if(mask&(uint64_t(1)<<i)) {
                    unsigned shift=8*(i%4);
                    auto& word=memory[address][i/4];
                    word=(word&~(0xffU<<shift))|(payload[i/4]&(0xffU<<shift));
                }
                ++writes;
            } else ++reads;
        }
        dut.clk=1;dut.eval();
        if(complete) pending=false;
        if(dut.fault) { std::cerr<<"CPU fault\n";return 4; }
        if(dut.report_valid) {
            if(results>=35) return 5;
            int32_t expected=0;
            for(unsigned k=0;k<11;++k)
                expected+=(int(((results/7)*11+k)%17)-8)*(int((k*7+results%7)%13)-6);
            if(dut.report_data!=uint32_t(expected)) return 6;
            ++results;
        }
        if(dut.exit_valid) {
            if(dut.exit_code || results!=35 || reads<8192 || writes<8192) {
                std::cerr<<"wide DDR exit="<<dut.exit_code<<" results="<<results<<'\n';return 7;
            }
            std::cout<<"PASS real VexRiscv -> registered bridges -> 512-bit memory -> TPU: "
                     <<reads<<" reads, "<<writes<<" writes, 35 signed results, "<<cycle<<" cycles\n";
            return 0;
        }
    }
    std::cerr<<"Timeout PC="<<std::hex<<dut.pc_debug<<'\n';return 8;
}
