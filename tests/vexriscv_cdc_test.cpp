#include "Vvexriscv_ddr_wide_test_top.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <string>
#include <unordered_map>

int main(int argc, char **argv) {
    if (argc > 2 || (argc == 2 && std::string(argv[1]) != "--slow-cpu")) return 9;
    const unsigned cpu_period = argc == 2 ? 16 : 10;
    Vvexriscv_ddr_wide_test_top dut;
    std::unordered_map<uint32_t,std::array<uint32_t,16>> memory;
    unsigned reads=0,writes=0,results=0,delay=0;
    bool pending=false;
    uint32_t address=0,rng=0x193075ab;
    uint64_t mask=0;
    bool write=false;
    std::array<uint32_t,16> payload{};
    dut.uart_rx=1;dut.m_ack=0;dut.m_err=0;dut.clk=0;dut.memory_clk=0;
    for (unsigned tick=0;tick<500000000;++tick) {
        const bool next_cpu=tick%cpu_period>=cpu_period/2, next_mem=(tick+3)%12>=6;
        const bool cpu_rise=next_cpu && !dut.clk, mem_rise=next_mem && !dut.memory_clk;
        dut.rst=tick<100;dut.ready_to_run=tick>240;
        dut.eval();
        bool complete=false;
        if(mem_rise) {
        rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;
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
        complete=dut.m_cyc && dut.m_stb && dut.m_ack;
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
        }
        dut.clk=next_cpu;dut.memory_clk=next_mem;dut.eval();
        if(complete) pending=false;
        if(dut.fault) { std::cerr<<"CPU fault\n";return 4; }
        if(cpu_rise && dut.report_valid) {
            if(results>=35) return 5;
            int32_t expected=0;
            for(unsigned k=0;k<11;++k)
                expected+=(int(((results/7)*11+k)%17)-8)*(int((k*7+results%7)%13)-6);
            if(dut.report_data!=uint32_t(expected)) return 6;
            ++results;
        }
        if(cpu_rise && dut.exit_valid) {
            if(dut.exit_code || results!=35 || reads<8192 || writes<8192) {
                std::cerr<<"wide DDR exit="<<dut.exit_code<<" results="<<results<<'\n';return 7;
            }
            std::cout<<"PASS real VexRiscv -> "<<1000.0/cpu_period<<"/83.333 MHz CDC -> registered bridges -> 512-bit memory -> TPU: "
                     <<reads<<" reads, "<<writes<<" writes, 35 signed results, "<<tick/cpu_period<<" CPU cycles\n";
            return 0;
        }
    }
    std::cerr<<"Timeout PC="<<std::hex<<dut.pc_debug<<'\n';return 8;
}
