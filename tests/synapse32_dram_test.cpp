#include "Vsynapse32_dram_soc.h"
#include <cstdint>
#include <iostream>
#include <unordered_map>

// Behavioral variable-latency memory, NOT a DDR PHY/calibration simulation.
int main() {
    Vsynapse32_dram_soc dut;
    std::unordered_map<uint32_t,uint32_t> memory;
    unsigned reads=0,writes=0,results=0,pending_delay=0;
    uint64_t read_bytes=0,write_bytes=0,request_stall_cycles=0;
    uint64_t response_latency_cycles=0,completed_transactions=0;
    unsigned accepted_cycle=0;
    bool pending=false;
    uint32_t pending_data=0;
    uint32_t rng=0x193075ab;
    dut.uart_rx=1;
    dut.ext_resp_valid=0; dut.ext_resp_error=0; dut.ext_resp_rdata=0;
    for (unsigned cycle=0; cycle<50000000; ++cycle) {
        rng^=rng<<13; rng^=rng>>17; rng^=rng<<5;
        dut.clk=0; dut.rst=cycle<8; dut.ready_to_run=cycle>20;
        dut.ext_req_ready=!pending && (rng&3)!=0;
        if (pending && pending_delay) --pending_delay;
        dut.ext_resp_valid=pending && pending_delay==0;
        dut.ext_resp_rdata=pending_data;
        dut.eval();
        const bool accept=dut.ext_req_valid && dut.ext_req_ready;
        const bool response=dut.ext_resp_valid && dut.ext_resp_ready;
        if (!dut.rst && dut.ext_req_valid && !dut.ext_req_ready)
            ++request_stall_cycles;
        const bool wr=dut.ext_req_write;
        const uint32_t addr=dut.ext_req_addr, data=dut.ext_req_wdata;
        const uint8_t strb=dut.ext_req_wstrb;
        dut.clk=1; dut.eval();
        if (response) {
            pending=false;
            response_latency_cycles+=cycle-accepted_cycle;
            ++completed_transactions;
        }
        if (accept) {
            if (pending || addr<0x40000000 || addr>=0x80000000 || (addr&3)) return 2;
            auto& word=memory[addr];
            if (wr) {
                for(unsigned lane=0;lane<4;++lane) if(strb&(1U<<lane))
                    word=(word&~(0xffU<<(lane*8)))|(data&(0xffU<<(lane*8)));
                ++writes;
                for(unsigned lane=0;lane<4;++lane)
                    if(strb&(1U<<lane)) ++write_bytes;
            } else { ++reads; read_bytes+=4; }
            accepted_cycle=cycle;
            pending=true; pending_delay=1+(rng%19); pending_data=word;
        }
        if (dut.fault) {
            std::cerr<<"CPU memory fault at PC=0x"<<std::hex<<dut.pc_debug<<'\n'; return 3;
        }
        if (dut.report_valid) {
            if(results>=35) return 4;
            int32_t expected=0;
            for(unsigned k=0;k<11;++k)
                expected+=(int(((results/7)*11+k)%17)-8)*(int((k*7+results%7)%13)-6);
            if(dut.report_data!=uint32_t(expected)) return 5;
            ++results;
        }
        if(dut.exit_valid) {
            if(dut.exit_code || results!=35 || reads<8192 || writes<8192) {
                std::cerr<<"DDR firmware exit="<<dut.exit_code<<" results="<<results
                         <<" reads="<<reads<<" writes="<<writes<<'\n'; return 6;
            }
            std::cout<<"PASS Synapse32 variable-latency DRAM -> TPU: "<<reads<<" reads, "
                     <<writes<<" writes, 35 signed results, "<<cycle<<" system cycles\n";
            // Diagnostic workload metrics, not physical DDR bandwidth or CPU IPC.
            // Count elapsed periods from the first sampled edge (cycle zero).
            std::cout<<"METRICS {\"schema\":1,\"workload\":\"dram-selftest-gemm-5x11x7-v1\","
                     <<"\"memory_model\":\"cycle-xorshift-193075ab-delay1to19-v1\","
                     <<"\"system_cycles\":"<<cycle
                     <<",\"external_reads\":"<<reads<<",\"external_writes\":"<<writes
                     <<",\"external_read_bytes\":"<<read_bytes
                     <<",\"external_write_bytes\":"<<write_bytes
                     <<",\"completed_transactions\":"<<completed_transactions
                     <<",\"request_stall_cycles\":"<<request_stall_cycles
                     <<",\"response_latency_cycles\":"<<response_latency_cycles
                     <<",\"checked_results\":"<<results<<"}\n";
            return 0;
        }
    }
    std::cerr<<"Timeout PC=0x"<<std::hex<<dut.pc_debug<<'\n';return 7;
}
