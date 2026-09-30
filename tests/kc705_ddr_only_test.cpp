#include "Vkc705_ddr_engine.h"
#include "csr_map.h"
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>

using Burst = std::array<uint32_t, 16>;
static void require(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}

struct Model {
    std::map<uint32_t, Burst> memory;
    std::map<unsigned, unsigned> csr;
    std::array<unsigned, 8> wd{}, dqs{}, rd{}, rs{}, ws{};
    unsigned select=0, wl=0, reads=0, writes=0, masks=0;
    uint64_t reset_low_at=0, reset_high_at=0;
    bool reset_low_seen=false, reset_high_seen=false, cke_seen=false, hardware_control=false;
    std::string mode;
    explicit Model(std::string m): mode(std::move(m)) {}

    void write_csr(unsigned address, unsigned data, uint64_t cycle) {
        csr[address] = data;
        if (address == sdram_dfii_control) {
            if (data == 0) { reset_low_at=cycle; reset_low_seen=true; }
            if (data == 8) {
                require(reset_low_seen && cycle-reset_low_at >= 20000, "reset low shorter than 200 us");
                reset_high_at=cycle; reset_high_seen=true;
            }
            if (data == 14) {
                require(reset_high_seen && cycle-reset_high_at >= 50000, "CKE raised before 500 us");
                cke_seen=true;
            }
            if (data == 1) {
                require(cke_seen && !wl, "native control before initialization/write leveling finished");
                hardware_control=true;
            }
        }
        if (address == ddrphy_dly_sel) select=data;
        if (address == ddrphy_wlevel_en) wl=data;
        for (unsigned i=0;i<8;++i) if (select & (1u<<i)) {
            if (address == ddrphy_wdly_dq_rst) wd[i]=0;
            if (address == ddrphy_wdly_dqs_rst) dqs[i]=0;
            if (address == ddrphy_rdly_dq_rst) rd[i]=0;
            if (address == ddrphy_rdly_dq_bitslip_rst) rs[i]=0;
            if (address == ddrphy_wdly_dq_bitslip_rst) ws[i]=0;
            if (address == ddrphy_wdly_dq_inc) wd[i]=(wd[i]+1)%32;
            if (address == ddrphy_wdly_dqs_inc) dqs[i]=(dqs[i]+1)%32;
            if (address == ddrphy_rdly_dq_inc) rd[i]=(rd[i]+1)%32;
            if (address == ddrphy_rdly_dq_bitslip) rs[i]=(rs[i]+1)%8;
            if (address == ddrphy_wdly_dq_bitslip) ws[i]=(ws[i]+1)%8;
        }
    }
    unsigned read_csr(unsigned address) {
        if (address == sdram_dfii_pi0_rddata || address == sdram_dfii_pi0_rddata+1) {
            require(wl, "write-level read outside write-level mode");
            unsigned base = address == sdram_dfii_pi0_rddata ? 4 : 0, result=0;
            for (unsigned j=0;j<4;++j) {
                unsigned lane=base+j;
                bool high = dqs[lane] >= 3+lane && dqs[lane] <= 15+lane;
                if (mode == "write-level" && lane == 6) high=true; // no edge
                if (mode == "write-level-zero" && lane == 6) high=false;
                result |= unsigned(high) << (j*8);
            }
            return result;
        }
        return csr[address];
    }
    bool trained(unsigned lane) const {
        bool eye = (rs[lane] == lane && rd[lane] >= 4+lane && rd[lane] <= 10+lane) ||
                   (rs[lane] == (lane+1)%8 && rd[lane] >= 20 && rd[lane] <= 23);
        if (mode == "narrow-eye" && lane == 7)
            eye = rs[lane] == lane && rd[lane] >= 7 && rd[lane] <= 8;
        return wd[lane] == 3+lane && dqs[lane] == 3+lane &&
               ws[lane] == (lane+2)%8 && eye &&
               !(mode == "read-eye" && lane == 7);
    }
    void access(Vkc705_ddr_engine &dut) {
        require(hardware_control, "memory transaction before hardware control");
        uint32_t address=dut.mem_adr;
        if (mode == "alias" && dut.stage == 3) address &= ~(1u<<10);
        auto &data=memory[address];
        if (dut.mem_we) {
            ++writes;
            uint64_t sel=dut.mem_sel;
            if (sel != UINT64_MAX) ++masks;
            if (mode == "mask") sel=UINT64_MAX;
            for (unsigned b=0;b<64;++b) if (sel & (uint64_t(1)<<b)) {
                unsigned shift=(b%4)*8, mask=255u<<shift;
                data[b/4]=(data[b/4]&~mask)|(dut.mem_dat_w[b/4]&mask);
            }
        } else {
            ++reads;
            Burst result=data;
            for (unsigned lane=0;lane<8;++lane) if (!trained(lane))
                result[lane/4] ^= 1u << ((lane%4)*8);
            if (mode == "data" && dut.stage == 3) result[13] ^= 0x8000;
            for (unsigned i=0;i<16;++i) dut.mem_dat_r[i]=result[i];
        }
    }
};

struct Pending {
    bool active=false, complete=false;
    unsigned delay=0, address=0, write=0;
    uint64_t select=0;
    Burst data{};
};

int main(int argc, char **argv) {
    try {
        require(argc == 2, "provide mode");
        std::string mode=argv[1];
        Vkc705_ddr_engine dut;
        Model model(mode);
        Pending csr, mem;
        bool did_reset=false;
        unsigned transactions=0, terminal_cycles=0;
        for (uint64_t cycle=0;cycle<2000000;++cycle) {
            dut.sys_clk=0;
            dut.ctrl_ack=0; dut.ctrl_err=0; dut.mem_ack=0; dut.mem_err=0;
            bool reset = cycle < 4;
            if (mode == "reset" && !did_reset && dut.stage == 2 && mem.active && !mem.complete) {
                reset=true; did_reset=true;
                model=Model(mode); csr=Pending{}; mem=Pending{};
            }
            dut.sys_rst=reset;
            dut.eval();
            if (!reset) {
                require(!(dut.passed && dut.failed), "simultaneous pass and fail");
                require(!(dut.ctrl_cyc && dut.mem_cyc), "overlapping independent requests");
                auto bus = [&](bool control, Pending &p) {
                    bool cyc=control?dut.ctrl_cyc:dut.mem_cyc;
                    bool stb=control?dut.ctrl_stb:dut.mem_stb;
                    unsigned adr=control?dut.ctrl_adr:dut.mem_adr;
                    unsigned we=control?dut.ctrl_we:dut.mem_we;
                    uint64_t sel=control?dut.ctrl_sel:dut.mem_sel;
                    Burst data{};
                    if (control) data[0]=dut.ctrl_dat_w;
                    else for (unsigned i=0;i<16;++i) data[i]=dut.mem_dat_w[i];
                    if (!cyc) { p=Pending{}; return; }
                    require(stb, "CYC without STB");
                    if (!p.active) {
                        p.active=true; p.delay=(++transactions*7)%9;
                        p.address=adr; p.write=we; p.select=sel; p.data=data;
                    } else {
                        require(!p.complete, "request not released after ACK");
                        require(p.address==adr && p.write==we && p.select==sel && p.data==data,
                                "payload changed under backpressure");
                    }
                    if (mode == (control?"csr-timeout":"memory-timeout")) return;
                    if (p.delay) { --p.delay; return; }
                    p.complete=true;
                    bool error=mode==(control?"csr-error":"memory-error");
                    if (control) {
                        dut.ctrl_err=error; dut.ctrl_ack=!error;
                        if (!error) {
                            if (we) model.write_csr(adr, data[0], cycle);
                            else dut.ctrl_dat_r=model.read_csr(adr);
                        }
                    } else {
                        dut.mem_err=error; dut.mem_ack=!error;
                        if (!error) model.access(dut);
                    }
                };
                bus(true, csr); bus(false, mem);
            }
            dut.eval(); dut.sys_clk=1; dut.eval();
            if (dut.passed || dut.failed) {
                if (dut.mem_cyc || dut.ctrl_cyc)
                    std::cerr << "terminal cycle=" << cycle << " pass=" << unsigned(dut.passed)
                              << " fail=" << unsigned(dut.failed) << " code=" << unsigned(dut.failure_code)
                              << " stage=" << unsigned(dut.stage) << " ctrl=" << unsigned(dut.ctrl_cyc)
                              << " mem=" << unsigned(dut.mem_cyc) << '\n';
                require(!dut.busy, "terminal result left busy set");
                require(!dut.mem_cyc && !dut.ctrl_cyc, "traffic continued after terminal result");
                if (++terminal_cycles < 20) continue;
                unsigned expected = mode=="pass" || mode=="reset" ? 0 :
                    mode=="write-level" || mode=="write-level-zero" ? 2 :
                    mode=="read-eye" || mode=="narrow-eye" ? 4 :
                    mode=="csr-timeout" || mode=="csr-error" ? 1 :
                    mode=="memory-timeout" || mode=="memory-error" ? 3 : 5;
                if (dut.failure_code != expected)
                    std::cerr << "unexpected result: code=" << unsigned(dut.failure_code)
                              << " address=" << dut.failure_address << " lanes=" << unsigned(dut.failure_lanes)
                              << " reads=" << model.reads << " writes=" << model.writes
                              << " masks=" << model.masks << '\n';
                require(dut.failure_code==expected && dut.passed==(expected==0) && dut.failed==(expected!=0),
                        "wrong terminal result");
                if (!expected) {
                    require(dut.initialized && dut.calibrated, "BIST passed without calibration");
                    require(model.masks==64, "did not test every byte enable");
                    for (unsigned i=0;i<8;++i)
                        require(model.rd[i]==7+i && model.rs[i]==i && model.trained(i), "wrong longest eye center");
                    require(mode!="reset" || did_reset, "reset case did not reset");
                }
                std::cout << "PASS " << mode << ": cycles=" << cycle << " code=" << expected
                          << " reads=" << model.reads << " writes=" << model.writes << '\n';
                return 0;
            }
        }
        throw std::runtime_error("simulation timed out");
    } catch (const std::exception &e) {
        std::cerr << "FAIL: " << e.what() << '\n'; return 1;
    }
}
