// Transport variant of mmio_rtl_test.cpp. Uses the real C mailbox driver.
#include "Vsynapse32_tpu_peripheral.h"
#include "tiny3tpu_axis_mailbox.h"
struct Simulation {
    Vsynapse32_tpu_peripheral dut;
    tiny3tpu_axis_mailbox mailbox{};
    bool delayed_poll = false;
    unsigned launches = 0;
    void tick() {
        dut.clk=0; dut.eval(); dut.clk=1; dut.eval(); dut.clk=0; dut.eval();
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
    const int status=tiny3tpu_axis_mailbox_write32(&s.mailbox,offset,value);
    if (!status && offset==0 && value==1) {
        ++s.launches; // Response is generated only after the AXI write completes.
        if(s.delayed_poll) for(unsigned i=0;i<500;++i) s.tick();
    }
    return status;
}
static int read32(void *user, uint32_t offset, uint32_t *value) {
    auto& s=*static_cast<Simulation*>(user);
    return tiny3tpu_axis_mailbox_read32(&s.mailbox,offset,value);
}
