#include "Vdma_fixture.h"
#include "axi_dma_memory_model.hpp"
#include <iostream>

int main() {
    try {
        Vdma_fixture dut;
        std::unordered_map<uint32_t,uint32_t> memory;
        AxiDmaMemory ram(memory);
        unsigned cycles=0,checks=0;
        auto tick=[&]() {
            dut.clk=0; ram.drive(dut); dut.eval(); ram.capture(dut);
            dut.clk=1; dut.eval(); ram.commit(); ++cycles;
        };
        auto reset=[&]() {
            dut.rst=1; dut.cpu_wr_en=0; dut.cpu_rd_en=0; dut.legacy_idle=1; dut.cpu_wstrb=15;
            for(unsigned i=0;i<8;++i) tick();
            dut.rst=0; tick();
        };
        auto write=[&](unsigned addr,uint32_t data) {
            dut.cpu_addr=addr; dut.cpu_wdata=data; dut.cpu_wr_en=1; tick(); dut.cpu_wr_en=0;
        };
        auto status=[&]() {
            dut.cpu_rd_en=1; dut.cpu_addr=0x10; dut.eval();
            const uint32_t value=dut.cpu_rdata; dut.cpu_rd_en=0; return value;
        };
        auto finish=[&]() {
            for(unsigned i=0;i<500000;++i) {
                tick(); if(status()&2) return status();
            }
            throw std::runtime_error("DMA completion timeout");
        };
        reset();
        const unsigned counts[]={1,2,7,8,9,193,1025};
        for(unsigned commands:counts) {
            const uint32_t tx=0x40000ff8,rx=0x40010004;
            for(unsigned i=0;i<commands;++i) {
                memory[tx+8*i]=0x10; memory[tx+8*i+4]=0; // Read idle TPU STATUS.
                memory[rx+8*i]=memory[rx+8*i+4]=0xdeadbeef;
            }
            const auto reads=ram.read_beats,writes=ram.write_beats;
            write(0,tx); write(4,rx); write(8,commands*8); write(12,1);
            AxiDmaMemory::require(finish()==2,"successful DMA status");
            AxiDmaMemory::require(!ram.writing && !ram.bv && !ram.bpending,"DONE preceded final write response");
            for(unsigned i=0;i<commands;++i)
                AxiDmaMemory::require(memory[rx+8*i]==0 && memory[rx+8*i+4]==0,"DMA response ordering/data");
            AxiDmaMemory::require(ram.read_beats-reads==2*commands && ram.write_beats-writes==2*commands,"DMA exact lengths");
            write(12,2); AxiDmaMemory::require(status()==0,"ACK clears completion"); ++checks;
        }
        // Invalid descriptors must not issue any memory transaction.
        const uint32_t invalid[][3]={{0x40000000,0x40010000,0},{0x40000000,0x40010000,7},
            {0x40000000,0x40010000,65536},{0x40000001,0x40010000,8},
            {0x30000000,0x40010000,8},{0x7ffffffc,0x40010000,8},
            {0x40000000,0x40000004,16}};
        for(const auto& config:invalid) {
            const auto before=ram.read_bursts+ram.write_bursts;
            write(0,config[0]);write(4,config[1]);write(8,config[2]);write(12,1);
            AxiDmaMemory::require(status()==6,"invalid descriptor rejected");
            for(unsigned i=0;i<8;++i) tick();
            AxiDmaMemory::require(ram.read_bursts+ram.write_bursts==before,"invalid descriptor touched RAM");
            write(12,2); ++checks;
        }
        // Each descriptor register can be the final write before START.
        // Cached span ends must reflect that write on the very next cycle.
        for(unsigned last: {0U,4U,8U}) {
            const auto before=ram.read_bursts+ram.write_bursts;
            write(0,0x40000000); write(4,0x40001000); write(8,8);
            if(last==0) { write(0,0x40001000); }
            if(last==4) { write(4,0x40000000); }
            if(last==8) { write(8,8192); }
            write(12,1);
            AxiDmaMemory::require(status()==6,"final descriptor write was not validated");
            for(unsigned i=0;i<8;++i) tick();
            AxiDmaMemory::require(ram.read_bursts+ram.write_bursts==before,"invalid final write touched RAM");
            write(12,2); ++checks;
        }
        memory[0x40000000]=0x10; memory[0x40000004]=0;
        for(unsigned last: {0U,4U,8U}) {
            write(0,last==0 ? 0x40010000:0x40000000);
            write(4,last==4 ? 0x40000000:0x40010000);
            write(8,last==8 ? 0:8);
            if(last==0) write(0,0x40000000);
            if(last==4) write(4,0x40010000);
            if(last==8) write(8,8);
            write(12,1);
            AxiDmaMemory::require(finish()==2,"valid final descriptor write was not accepted");
            write(12,2); ++checks;
        }
        for(unsigned kind=0;kind<4;++kind) {
            reset(); ram.read_error=kind==1; ram.write_error=kind==2;
            memory[0x40000000]=kind==3 ? 0xfc:0x10; memory[0x40000004]=0;
            write(0,0x40000000);write(4,0x40010000);write(8,8);
            if(kind==0) {
                dut.legacy_idle=0;write(12,1);
                AxiDmaMemory::require(status()==6,"DMA stole legacy ownership");
            } else {
                write(12,1); AxiDmaMemory::require((finish()&6)==6,"DMA error not propagated");
            }
            ++checks;
        }
        ram.read_error=ram.write_error=false;reset();
        // Firmware can rely on aggregate ERROR at the first visible DONE.
        // Check an error at each end and in the middle of a full load batch.
        for(unsigned bad: {0U,96U,192U}) {
            reset();
            for(unsigned i=0;i<193;++i) {
                memory[0x40000000+8*i]=i==bad ? 0xfc:0x10;
                memory[0x40000004+8*i]=0;
            }
            write(0,0x40000000);write(4,0x40010000);write(8,193*8);write(12,1);
            AxiDmaMemory::require(finish()==6,"aggregate command error missing at DONE");
            for(unsigned i=0;i<193;++i)
                AxiDmaMemory::require((memory[0x40010000+8*i]!=0)==(i==bad),"command error position mismatch");
            write(12,2); AxiDmaMemory::require(status()==0,"error acknowledgment failed");
            ++checks;
        }
        reset();
        memory[0x40000000]=0x10; memory[0x40000004]=0;
        write(0,0x40000000);write(4,0x40010000);write(8,8);write(12,1);
        write(0,0x30000000);write(12,1);write(12,2);
        AxiDmaMemory::require(finish()==10,"busy misuse lost original transfer"); ++checks;
        // Reset the DMA, memory model and TPU together during transactions.
        for(unsigned delay: {1U,5U,13U,31U,67U}) {
            reset();
            for(unsigned i=0;i<32;++i) { memory[0x40000000+8*i]=0x10; memory[0x40000004+8*i]=0; }
            write(0,0x40000000);write(4,0x40010000);write(8,256);write(12,1);
            for(unsigned i=0;i<delay;++i) tick();
            reset();
            AxiDmaMemory::require(status()==0 && !dut.irq,"reset retained old ownership/completion");
            write(0,0x40000000);write(4,0x40010000);write(8,8);write(12,1);
            AxiDmaMemory::require(finish()==2 && memory[0x40010000]==0 && memory[0x40010004]==0,"post-reset transfer failed");
            ++checks;
        }
        std::cout<<"PASS open AXI DMA + TPU: "<<checks<<" cases, "<<ram.read_beats
                 <<" read beats, "<<ram.write_beats<<" write beats, "<<cycles<<" cycles\n";
        return 0;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n'; return 1;
    }
}
