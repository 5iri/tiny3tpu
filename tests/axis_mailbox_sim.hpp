// Transport variant of mmio_rtl_test.cpp. Uses the real C mailbox driver.
#include "Vsynapse32_tpu_peripheral.h"
#include "tiny3tpu_axis_mailbox.h"
#include "mmio_sim_metrics.hpp"
struct Simulation {
    Vsynapse32_tpu_peripheral dut;
    tiny3tpu_axis_mailbox mailbox{};
    bool delayed_poll = false;
    bool mask_accum_capability = false;
    bool mask_result_window_capability = false;
    unsigned launches = 0;
    MmioSimCounts counts;
    uint64_t simulated_ticks = 0;
    bool saw_accum_capability = false;
    bool saw_result_window_capability = false;
    void tick() {
        dut.clk=0; dut.eval(); dut.clk=1; dut.eval(); dut.clk=0; dut.eval();
        ++simulated_ticks;
    }
    static int local_read(void *user, uint32_t offset, uint32_t *value) {
        auto& s=*static_cast<Simulation*>(user);
        s.dut.cpu_addr=offset; s.dut.cpu_rd_en=1; s.dut.eval();
        *value=s.dut.cpu_rdata;
        s.tick(); s.dut.cpu_rd_en=0; s.dut.eval();
        return 0;
    }
    static int local_write(void *user, uint32_t offset, uint32_t value) {
        auto& s=*static_cast<Simulation*>(user);
        s.dut.cpu_addr=offset; s.dut.cpu_wdata=value;
        s.dut.cpu_wstrb=15; s.dut.cpu_wr_en=1;
        s.tick(); s.dut.cpu_wr_en=0; s.dut.eval();
        return 0;
    }
    Simulation() {
        dut.rst_n=0; dut.cpu_wr_en=0; dut.cpu_rd_en=0;
        dut.cpu_addr=0; dut.cpu_wdata=0; dut.cpu_wstrb=0;
        tick(); tick(); dut.rst_n=1; tick();
        tiny3tpu_axis_mailbox_init(&mailbox,this,local_read,local_write,1000);
    }
};
static int write32(void *user, uint32_t offset, uint32_t value) {
    auto& s=*static_cast<Simulation*>(user);
    const uint64_t begin=s.simulated_ticks;
    const int status=tiny3tpu_axis_mailbox_write32(&s.mailbox,offset,value);
    const uint64_t elapsed=s.simulated_ticks-begin;
    if (!status) record_write(s,offset,value,elapsed);
    if (!status && offset==SIM_REG_CTRL && (value&TINY3TPU_MMIO_CTRL_START)) {
        ++s.launches; // Response is generated only after the AXI write completes.
        if(s.delayed_poll) for(unsigned i=0;i<500;++i) s.tick();
    }
    return status;
}
static int read32(void *user, uint32_t offset, uint32_t *value) {
    auto& s=*static_cast<Simulation*>(user);
    const uint64_t begin=s.simulated_ticks;
    const int status=tiny3tpu_axis_mailbox_read32(&s.mailbox,offset,value);
    if (!status) {
        if (offset==SIM_REG_STATUS && s.mask_accum_capability)
            *value &= ~TINY3TPU_MMIO_STATUS_ACCUM_CAP;
        if (offset==SIM_REG_STATUS && s.mask_result_window_capability)
            *value &= ~TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP;
        record_read(s,offset,*value,s.simulated_ticks-begin);
    }
    return status;
}
