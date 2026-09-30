#include <stdint.h>
#include <stdio.h>
#include <generated/csr.h>
#include <generated/sdram_phy.h>
#include <liblitedram/sdram.h>
#include <liblitedram/accessors.h>

int kc705_ddr_csr_check(void)
{
    for (unsigned p=0;p<4;++p)
        for (unsigned w=0;w<4;++w)
            csr_write_simple(UINT32_C(0x10203040)*(p+1)^UINT32_C(0x55aa5500)^w,
                             sdram_dfii_pix_wrdata_addr(p)+4*w);
    for (unsigned p=0;p<4;++p)
        for (unsigned w=0;w<4;++w) {
            uint32_t expected=UINT32_C(0x10203040)*(p+1)^UINT32_C(0x55aa5500)^w;
            uint32_t actual=csr_read_simple(sdram_dfii_pix_wrdata_addr(p)+4*w);
            if (expected!=actual) {
                printf("DFI CSR FAIL p%u w%u expected %08x got %08x\n",p,w,(unsigned)expected,(unsigned)actual);
                return 0;
            }
        }
    puts("DFI CSR: all 512 write-data bits read back correctly");
    return 1;
}

static void read_mpr(unsigned phase, uint8_t data[4][16])
{
#ifdef TINY3TPU_DDR_PAD_LOOPBACK
    // Drive a write-data burst while keeping DRAM chip select inactive.
    // The input receiver observes the same physical DQ pad; no DIMM READ
    // or WRITE command is issued, so the DIMM remains high impedance.
    const int command=DFII_COMMAND_WRDATA|DFII_COMMAND_RDDATA;
#else
    const int command=DFII_COMMAND_CAS|DFII_COMMAND_CS|DFII_COMMAND_RDDATA;
#endif
    switch(phase) {
        case 0: command_p0(command);break;
        case 1: command_p1(command);break;
        case 2: command_p2(command);break;
        case 3: command_p3(command);break;
    }
    cdelay(100);
    for(unsigned p=0;p<4;++p)
        csr_rd_buf_uint8(sdram_dfii_pix_rddata_addr(p),data[p],16);
}

static unsigned mpr_errors(uint8_t data[4][16],unsigned module)
{
    unsigned errors=0;
    for(unsigned p=0;p<4;++p) {
        // DDR3 guarantees the MPR pattern on DQ0 of each x8 chip only.
        errors+=data[p][15-module]&1U;
        errors+=(data[p][7-module]^0xffU)&1U;
    }
    return errors;
}

#ifdef CSR_DDRPHY_TRACE_ARM_ADDR
static void dump_read_history(unsigned phase, uint8_t data[4][16])
{
    ddrphy_trace_arm_write(1);
    read_mpr(phase,data);
    printf("MPR history done=%u valid=%04x (lanes m7..m0, time in each byte LSB first):\n",
           ddrphy_trace_done_read(), ddrphy_trace_valid_read());
    for(unsigned cycle=0;cycle<16;++cycle) {
        ddrphy_trace_index_write(cycle);
        uint64_t sample=ddrphy_trace_data_read();
        printf("cycle%u: %08x%08x\n",cycle,(unsigned)(sample>>32),(unsigned)sample);
    }
}
#endif

#ifdef TINY3TPU_DDR_HISTORY_SCAN
#ifndef CSR_DDRPHY_TRACE_ARM_ADDR
#error "History scanning needs the hardware read recorder"
#endif
static void read_wave(unsigned phase, uint64_t wave[8])
{
    uint8_t data[4][16];
    ddrphy_trace_arm_write(1);
    read_mpr(phase,data);
    for(unsigned m=0;m<8;++m) wave[m]=0;
    for(unsigned cycle=4;cycle<12;++cycle) {
        ddrphy_trace_index_write(cycle);
        uint64_t sample=ddrphy_trace_data_read();
        for(unsigned m=0;m<8;++m)
            wave[m]|=((sample>>(8*m))&255ULL)<<(8*(cycle-4));
    }
}

static unsigned count_bits(unsigned value)
{
    unsigned n=0;
    for(;value;value&=value-1) ++n;
    return n;
}

static unsigned wave_error(uint64_t wave, unsigned *start, unsigned *pattern)
{
    unsigned best=9;
    for(unsigned s=0;s<=56;++s) {
        unsigned value=(unsigned)(wave>>s)&255U;
#ifdef TINY3TPU_DDR_PAD_PATTERN
        unsigned expected=TINY3TPU_DDR_PAD_PATTERN;
#else
        unsigned expected=0xaaU;
#endif
        unsigned errors=count_bits(value^expected);
        // An alternating MPR pattern locates the sampling eye; the exact
        // burst boundary must subsequently be checked with written data.
#ifndef TINY3TPU_DDR_PAD_PATTERN
        if(errors>4) {errors=8-errors;expected=0x55U;}
#endif
        if(errors<best) {best=errors;*start=s;*pattern=expected;}
    }
    return best;
}

static void scan_read_history(void)
{
#ifdef TINY3TPU_DDR_PAD_LOOPBACK
#ifdef TINY3TPU_DDR_PAD_ZERO
    puts("PAD LOOPBACK: FPGA drives zero data, DRAM CS inactive");
#elif defined(TINY3TPU_DDR_PAD_PATTERN)
    printf("PAD LOOPBACK: FPGA drives pattern %02x, DRAM CS inactive\n",TINY3TPU_DDR_PAD_PATTERN);
#else
    puts("PAD LOOPBACK: FPGA drives alternating data, DRAM CS inactive");
#endif
    ddrphy_dly_sel_write(255);
    ddrphy_wdly_dq_rst_write(1);
    ddrphy_wdly_dq_bitslip_rst_write(1);
    for(unsigned p=0;p<4;++p)
        for(unsigned w=0;w<4;++w)
            csr_write_simple(
#ifdef TINY3TPU_DDR_PAD_ZERO
                0,
#elif defined(TINY3TPU_DDR_PAD_PATTERN)
                (TINY3TPU_DDR_PAD_PATTERN & (1U<<(2*p+(w<2))))?UINT32_MAX:0,
#else
                w<2?UINT32_MAX:0,
#endif
                sdram_dfii_pix_wrdata_addr(p)+4*w);
#else
    puts("MPR history sweep: all burst positions, both alternating polarities");
#endif
    uint64_t wave[8];
    unsigned winner_error=65,winner_width=0,winner_cmd=0,winner_phase=0,winner_tap[8];
    ddrphy_dly_sel_write(255);
    ddrphy_rdly_dq_bitslip_rst_write(1);
    ddrphy_cdly_rst_write(1);
    for(unsigned cmd=0;cmd<32;++cmd) {
        for(unsigned phase=0;phase<4;++phase) {
            unsigned best[8],tap_center[8],best_width[8]={0},width[8]={0},start[8];
            for(unsigned m=0;m<8;++m) best[m]=9;
            ddrphy_rdly_dq_rst_write(1);
            for(unsigned tap=0;tap<32;++tap) {
                read_wave(phase,wave);
                for(unsigned m=0;m<8;++m) {
                    unsigned position,pattern;
                    unsigned errors=wave_error(wave[m],&position,&pattern);
                    if(errors<best[m]) {best[m]=errors;best_width[m]=0;width[m]=0;}
                    if(errors==best[m]) {
                        if(!width[m]) start[m]=tap;
                        ++width[m];
                        if(width[m]>best_width[m]) {
                            best_width[m]=width[m];tap_center[m]=start[m]+width[m]/2;
                        }
                    } else width[m]=0;
                }
                ddrphy_rdly_dq_inc_write(1);
            }
            unsigned sum=0,min_width=32;
            printf("HISTORY cmd%u phase%u error/tap/width:",cmd,phase);
            for(unsigned m=0;m<8;++m) {
                printf(" m%u=%u/%u/%u",m,best[m],tap_center[m],best_width[m]);
                sum+=best[m];if(best_width[m]<min_width) min_width=best_width[m];
            }
            putchar('\n');
            if(sum<winner_error || (sum==winner_error && min_width>winner_width)) {
                winner_error=sum;winner_width=min_width;winner_cmd=cmd;winner_phase=phase;
                for(unsigned m=0;m<8;++m) winner_tap[m]=tap_center[m];
            }
        }
        ddrphy_cdly_inc_write(1);
    }
    ddrphy_cdly_rst_write(1);
    for(unsigned c=0;c<winner_cmd;++c) ddrphy_cdly_inc_write(1);
    for(unsigned m=0;m<8;++m) {
        ddrphy_dly_sel_write(1U<<m);ddrphy_rdly_dq_rst_write(1);
        for(unsigned t=0;t<winner_tap[m];++t) ddrphy_rdly_dq_inc_write(1);
    }
    read_wave(winner_phase,wave);
    unsigned position[8],pattern[8],errors=0;
    printf("HISTORY selected cmd%u phase%u:\n",winner_cmd,winner_phase);
    for(unsigned m=0;m<8;++m) {
        unsigned e=wave_error(wave[m],&position[m],&pattern[m]);
        printf("m%u tap%u errors%u start%u pattern%02x wave=%08x%08x\n",
               m,winner_tap[m],e,position[m]+32,pattern[m],
               (unsigned)(wave[m]>>32),(unsigned)wave[m]);
    }
    // Freeze the chosen window and polarity for the repeatability check.
    for(unsigned repeat=0;repeat<16;++repeat) {
        read_wave(winner_phase,wave);
        for(unsigned m=0;m<8;++m)
            errors+=count_bits(((unsigned)(wave[m]>>position[m])&255U)^pattern[m]);
    }
    printf("HISTORY fixed-window repeat: %u errors in 1024 prime-DQ samples\n",errors);
    uint8_t data[4][16];dump_read_history(winner_phase,data);
}
#endif

#ifdef TINY3TPU_DDR_RETRAIN
#ifdef TINY3TPU_DDR_HISTORY_SCAN
#error "Retraining uses the fixed DFI capture window, not the history scanner"
#endif
static void issue_phase(unsigned phase, unsigned command)
{
    switch(phase) {
        case 0: command_p0(command);break;
        case 1: command_p1(command);break;
        case 2: command_p2(command);break;
        case 3: command_p3(command);break;
    }
}

static void written_errors(unsigned rdphase, unsigned wrphase, unsigned seed, unsigned errors[8])
{
    uint8_t expected[4][16],got[4][16];
    uint32_t state=UINT32_C(0x9e3779b9)^seed;
    for(unsigned p=0;p<4;++p) {
        for(unsigned b=0;b<16;++b) {
            state^=state<<13;state^=state>>17;state^=state<<5;
            expected[p][b]=(uint8_t)state;
#ifdef TINY3TPU_DDR_TRAIN_UNIFORM
            // Separate existence of a writable burst from its bit ordering.
            // The final 64-pattern check below still uses arbitrary data.
            if(seed==42 || seed==84) expected[p][b]=seed==42?0:255;
#endif
        }
        csr_wr_buf_uint8(sdram_dfii_pix_wrdata_addr(p),expected[p],16);
    }
    sdram_dfii_pi0_address_write(0);sdram_dfii_pi0_baddress_write(0);
    sdram_dfii_pi1_address_write(0);sdram_dfii_pi1_baddress_write(0);
    sdram_dfii_pi2_address_write(0);sdram_dfii_pi2_baddress_write(0);
    sdram_dfii_pi3_address_write(0);sdram_dfii_pi3_baddress_write(0);
    command_p0(DFII_COMMAND_RAS|DFII_COMMAND_CS);cdelay(100);
    issue_phase(wrphase,DFII_COMMAND_CAS|DFII_COMMAND_WE|DFII_COMMAND_CS|DFII_COMMAND_WRDATA);
    cdelay(100);
    read_mpr(rdphase,got);
    command_p0(DFII_COMMAND_RAS|DFII_COMMAND_WE|DFII_COMMAND_CS);cdelay(100);
    if(seed==UINT32_C(0x12340000))
        for(unsigned p=0;p<4;++p) {
            printf("DFI pattern p%u expected:",p);
            for(unsigned b=0;b<16;++b) printf(" %02x",expected[p][b]);
            printf(" got:");
            for(unsigned b=0;b<16;++b) printf(" %02x",got[p][b]);
            putchar('\n');
        }
    for(unsigned m=0;m<8;++m)
        for(unsigned p=0;p<4;++p) {
            unsigned a=expected[p][15-m]^got[p][15-m];
            unsigned b=expected[p][7-m]^got[p][7-m];
            for(;a;a&=a-1) ++errors[m];
            for(;b;b&=b-1) ++errors[m];
        }
}

static int train_writes(unsigned rdphase, unsigned cmd)
{
#ifdef TINY3TPU_DDR_TRAIN_UNIFORM
    puts("DFI write diagnostic: alternating all-zero/all-one bursts; arbitrary-data verification follows");
#else
    puts("DFI write training: frozen MPR read settings, two independent 512-bit patterns");
#endif
    sdram_write_leveling_force_cmd_delay(cmd,1);
    if(!sdram_write_leveling()) {puts("DFI write training: DQS leveling failed");return 0;}
    unsigned winner_error=1025,winner_phase=0,winner_width=0,winner_tap[8],winner_slip[8];
    for(unsigned phase=0;phase<4;++phase) {
        unsigned best[8],tap_center[8],slip_center[8],best_width[8]={0};
        for(unsigned m=0;m<8;++m) best[m]=129;
        ddrphy_wrphase_write(phase);ddrphy_dly_sel_write(255);
        ddrphy_wdly_dq_bitslip_rst_write(1);
        for(unsigned slip=0;slip<8;++slip) {
            unsigned width[8]={0},start[8];
            ddrphy_wdly_dq_rst_write(1);
            for(unsigned tap=0;tap<32;++tap) {
                unsigned errors[8]={0};
                written_errors(rdphase,phase,42,errors);
                written_errors(rdphase,phase,84,errors);
                for(unsigned m=0;m<8;++m) {
                    if(errors[m]<best[m]) {best[m]=errors[m];best_width[m]=0;width[m]=0;}
                    if(errors[m]==best[m]) {
                        if(!width[m]) start[m]=tap;
                        ++width[m];
                        if(width[m]>best_width[m]) {
                            best_width[m]=width[m];tap_center[m]=start[m]+width[m]/2;slip_center[m]=slip;
                        }
                    } else width[m]=0;
                }
                ddrphy_wdly_dq_inc_write(1);
            }
            ddrphy_wdly_dq_bitslip_write(1);
        }
        unsigned sum=0,min_width=32;
        printf("DFI WRITE phase%u error/slip/tap/width:",phase);
        for(unsigned m=0;m<8;++m) {
            printf(" m%u=%u/%u/%u/%u",m,best[m],slip_center[m],tap_center[m],best_width[m]);
            sum+=best[m];if(best_width[m]<min_width) min_width=best_width[m];
        }
        putchar('\n');
        if(sum<winner_error || (sum==winner_error && min_width>winner_width)) {
            winner_error=sum;winner_phase=phase;winner_width=min_width;
            for(unsigned m=0;m<8;++m) {winner_tap[m]=tap_center[m];winner_slip[m]=slip_center[m];}
        }
    }
    ddrphy_wrphase_write(winner_phase);
    for(unsigned m=0;m<8;++m) {
        ddrphy_dly_sel_write(1U<<m);ddrphy_wdly_dq_rst_write(1);ddrphy_wdly_dq_bitslip_rst_write(1);
        for(unsigned t=0;t<winner_tap[m];++t) ddrphy_wdly_dq_inc_write(1);
        for(unsigned s=0;s<winner_slip[m];++s) ddrphy_wdly_dq_bitslip_write(1);
    }
    unsigned errors[8]={0},total=0;
    for(unsigned repeat=0;repeat<64;++repeat)
        written_errors(rdphase,winner_phase,UINT32_C(0x12340000)+repeat,errors);
    for(unsigned m=0;m<8;++m) total+=errors[m];
    printf("DFI WRITE selected phase%u: %u errors in 32768 data bits\n",winner_phase,total);
    return winner_error==0 && total==0;
}
#endif

int kc705_ddr_phy_debug(void)
{
    int trained=0;
    puts("DDR diagnostic: MPR reads, full phase/bitslip/tap sweep");
    sdram_software_control_on();
    // Precharge all before entering DDR3's fixed-pattern read mode.
    sdram_dfii_pi0_address_write(0x400);
    sdram_dfii_pi0_baddress_write(0);
    command_p0(DFII_COMMAND_RAS|DFII_COMMAND_WE|DFII_COMMAND_CS);
    cdelay(100);
#ifdef TINY3TPU_DDR_RON40
    // Diagnostic source-impedance comparison for the explicit SSTL15 profile.
    // DDR3 MR1 A1=0 selects RZQ/6 (40 ohm), instead of RZQ/7 (34 ohm).
    puts("DDR diagnostic: DIMM output drive RZQ/6 (40 ohm)");
    sdram_mode_register_write(1,DDRX_MR_WRLVL_RESET & ~2);
    cdelay(100);
#endif
    sdram_mode_register_write(3,4);
    cdelay(100);
    sdram_dfii_pi0_address_write(0);sdram_dfii_pi0_baddress_write(0);
    sdram_dfii_pi1_address_write(0);sdram_dfii_pi1_baddress_write(0);
    sdram_dfii_pi2_address_write(0);sdram_dfii_pi2_baddress_write(0);
    sdram_dfii_pi3_address_write(0);sdram_dfii_pi3_baddress_write(0);
    ddrphy_dly_sel_write(0xff);
#ifdef TINY3TPU_DDR_HISTORY_SCAN
    scan_read_history();
#else
    unsigned winner_phase=0,winner_error=513,winner_cmd=0,winner_width=0;
    unsigned winner_tap[8],winner_slip[8];
    uint8_t data[4][16];
#ifdef CSR_DDRPHY_TRACE_ARM_ADDR
    ddrphy_rdphase_write(0);
    ddrphy_rdly_dq_bitslip_rst_write(1);
    ddrphy_rdly_dq_rst_write(1);
    dump_read_history(0,data);
#endif
    ddrphy_cdly_rst_write(1);
    for (unsigned cmd=0;cmd<32;++cmd) {
    cdelay(100);
    for (unsigned phase=0;phase<4;++phase) {
        unsigned best_error[8],best_tap[8],best_slip[8],best_width[8]={0};
        for(unsigned m=0;m<8;++m) best_error[m]=9;
        ddrphy_rdphase_write(phase);
        ddrphy_rdly_dq_bitslip_rst_write(1);
        for(unsigned slip=0;slip<8;++slip) {
            unsigned start[8],width[8]={0};
            ddrphy_rdly_dq_rst_write(1);
            for (unsigned tap=0;tap<32;++tap) {
                read_mpr(phase,data);
                for(unsigned m=0;m<8;++m) {
                    unsigned errors=mpr_errors(data,m);
                    if(errors<best_error[m]) {
                        best_error[m]=errors;best_tap[m]=tap;best_slip[m]=slip;
                        best_width[m]=0;width[m]=0;
                    }
                    if(errors==best_error[m]) {
                        if(!width[m]) start[m]=tap;
                        ++width[m];
                        if(width[m]>best_width[m]) {
                            best_width[m]=width[m];best_tap[m]=start[m]+width[m]/2;best_slip[m]=slip;
                        }
                    } else width[m]=0;
                }
                ddrphy_rdly_dq_inc_write(1);
            }
            ddrphy_rdly_dq_bitslip_write(1);
        }
        unsigned sum=0,min_width=32;
        printf("MPR cmd%u phase%u best error/slip/tap/width:",cmd,phase);
        for(unsigned m=0;m<8;++m) {
            printf(" m%u=%u/%u/%u/%u",m,best_error[m],best_slip[m],best_tap[m],best_width[m]);
            sum+=best_error[m];
            if(best_width[m]<min_width) min_width=best_width[m];
        }
        putchar('\n');
        if(sum<winner_error || (sum==winner_error && min_width>winner_width)) {
            winner_error=sum;winner_phase=phase;winner_cmd=cmd;
            winner_width=min_width;
            for(unsigned m=0;m<8;++m) {winner_tap[m]=best_tap[m];winner_slip[m]=best_slip[m];}
        }
    }
    ddrphy_cdly_inc_write(1);
    }
    ddrphy_cdly_rst_write(1);
    for(unsigned c=0;c<winner_cmd;++c) ddrphy_cdly_inc_write(1);
    ddrphy_rdphase_write(winner_phase);
    for(unsigned m=0;m<8;++m) {
        ddrphy_dly_sel_write(1U<<m);
        ddrphy_rdly_dq_bitslip_rst_write(1);ddrphy_rdly_dq_rst_write(1);
        for(unsigned s=0;s<winner_slip[m];++s) ddrphy_rdly_dq_bitslip_write(1);
        for(unsigned t=0;t<winner_tap[m];++t) ddrphy_rdly_dq_inc_write(1);
    }
    unsigned errors=0;
    for(unsigned repeat=0;repeat<16;++repeat) {
        read_mpr(winner_phase,data);
        for(unsigned m=0;m<8;++m) errors+=mpr_errors(data,m);
    }
    printf("MPR combined cmd%u phase%u: %u errors in 1024 prime-DQ samples\n",winner_cmd,winner_phase,errors);
    printf("MPR prime-DQ burst bits (expected aa):");
    for(unsigned m=0;m<8;++m) {
        unsigned bits=0;
        for(unsigned p=0;p<4;++p) {
            bits|=(data[p][15-m]&1U)<<(2*p);
            bits|=(data[p][7-m]&1U)<<(2*p+1);
        }
        printf(" m%u=%02x",m,bits);
    }
    putchar('\n');
#ifdef CSR_DDRPHY_TRACE_ARM_ADDR
    dump_read_history(winner_phase,data);
#endif
#endif
    sdram_mode_register_write(3,0);
#ifdef TINY3TPU_DDR_RETRAIN
    cdelay(100);
    if(errors==0) trained=train_writes(winner_phase,winner_cmd);
#endif
    ddrphy_dly_sel_write(0);
    sdram_software_control_off();
    return trained;
}
