#pragma once
#include <cstdint>
#include <stdexcept>
#include <unordered_map>

// Independent AXI channel backpressure and burst bookkeeping. One outstanding
// burst per direction; simultaneous read/write traffic shares the CPU's RAM.
struct AxiDmaMemory {
    std::unordered_map<uint32_t,uint32_t>& memory;
    uint32_t rng=0x29b3417e, ra=0,wa=0,rd=0;
    unsigned rn=0,wn=0,ri=0,wi=0,rdelay=0,bdelay=0;
    bool reading=false,writing=false,rv=false,bv=false,bpending=false;
    uint8_t rid=0,bid=0;
    uint64_t read_bursts=0,write_bursts=0,read_beats=0,write_beats=0;
    bool read_error=false,write_error=false;
    struct Edge {
        bool ar,rr,aw,ww,bb;
        uint32_t araddr,awaddr,wdata;
        unsigned arbeats,awbeats;
        uint8_t arid,awid,wstrb;
        bool wlast;
    } edge{};
    explicit AxiDmaMemory(std::unordered_map<uint32_t,uint32_t>& storage):memory(storage) {}
    static void require(bool condition,const char* message) {
        if(!condition) throw std::runtime_error(message);
    }
    template<class DUT> void drive(DUT& dut) {
        rng^=rng<<13; rng^=rng>>17; rng^=rng<<5;
        if(dut.rst) {
            reading=writing=rv=bv=bpending=false; rdelay=bdelay=0;
        } else {
            if(rdelay) --rdelay;
            if(bdelay) --bdelay;
            if(reading && !rv && !rdelay) { rd=memory[ra+4*ri]; rv=true; }
            if(bpending && !bdelay) { bv=true; bpending=false; }
        }
        dut.m_axi_arready=!dut.rst && !reading && (rng&3)!=0;
        dut.m_axi_rvalid=!dut.rst && rv;
        dut.m_axi_rdata=rd; dut.m_axi_rid=rid;
        dut.m_axi_rresp=read_error ? 2:0;
        dut.m_axi_rlast=reading && ri+1==rn;
        dut.m_axi_awready=!dut.rst && !writing && !bv && !bpending && (rng&12)!=0;
        dut.m_axi_wready=!dut.rst && writing && (rng&48)!=0;
        dut.m_axi_bvalid=!dut.rst && bv;
        dut.m_axi_bid=bid; dut.m_axi_bresp=write_error ? 2:0;
    }
    template<class DUT> void capture(const DUT& dut) {
        edge.ar=dut.m_axi_arvalid && dut.m_axi_arready;
        edge.rr=dut.m_axi_rvalid && dut.m_axi_rready;
        edge.aw=dut.m_axi_awvalid && dut.m_axi_awready;
        edge.ww=dut.m_axi_wvalid && dut.m_axi_wready;
        edge.bb=dut.m_axi_bvalid && dut.m_axi_bready;
        edge.araddr=dut.m_axi_araddr; edge.arbeats=dut.m_axi_arlen+1; edge.arid=dut.m_axi_arid;
        edge.awaddr=dut.m_axi_awaddr; edge.awbeats=dut.m_axi_awlen+1; edge.awid=dut.m_axi_awid;
        edge.wdata=dut.m_axi_wdata; edge.wstrb=dut.m_axi_wstrb; edge.wlast=dut.m_axi_wlast;
        if(edge.ar) require(dut.m_axi_arburst==1 && dut.m_axi_arsize==2 && !dut.m_axi_arlock,"invalid AXI read burst");
        if(edge.aw) require(dut.m_axi_awburst==1 && dut.m_axi_awsize==2 && !dut.m_axi_awlock,"invalid AXI write burst");
    }
    static void check_address(uint32_t address,unsigned beats) {
        require(!(address&3) && address>=0x40000000 && uint64_t(address)+4*beats<=0x80000000ULL,"DMA address outside DDR");
        require(beats<=16 && (address&4095)+beats*4<=4096,"DMA burst exceeds limit or crosses 4 KiB");
    }
    void commit() {
        if(edge.ar) {
            check_address(edge.araddr,edge.arbeats);
            require(!reading,"read burst overlap");
            reading=true; ra=edge.araddr; rn=edge.arbeats; ri=0; rid=edge.arid;
            rdelay=1+(rng%11); ++read_bursts;
        }
        if(edge.rr) {
            require(reading && rv,"unexpected read beat");
            rv=false; ++ri; ++read_beats;
            if(ri==rn) reading=false;
            else rdelay=1+(rng%7);
        }
        if(edge.aw) {
            check_address(edge.awaddr,edge.awbeats);
            require(!writing && !bv && !bpending,"write burst overlap");
            writing=true; wa=edge.awaddr; wn=edge.awbeats; wi=0; bid=edge.awid; ++write_bursts;
        }
        if(edge.ww) {
            require(writing && edge.wlast==(wi+1==wn),"unexpected WLAST or write beat");
            auto& word=memory[wa+4*wi];
            for(unsigned lane=0;lane<4;++lane) if(edge.wstrb&(1U<<lane))
                word=(word&~(0xffU<<(8*lane)))|(edge.wdata&(0xffU<<(8*lane)));
            ++wi; ++write_beats;
            if(wi==wn) { writing=false; bpending=true; bdelay=1+(rng%13); }
        }
        if(edge.bb) { require(bv,"unexpected B response"); bv=false; }
    }
};
