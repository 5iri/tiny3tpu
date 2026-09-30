#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <generated/csr.h>
#include <liblitedram/sdram.h>

#define UART ((volatile uint32_t *)(uintptr_t)UINT32_C(0x20000000))
int synapse32_dram_selftest(void);
#ifdef TINY3TPU_DDR_STRESS
int kc705_ddr_stress(void);
#endif
#ifdef TINY3TPU_DDR_DEBUG
int kc705_ddr_csr_check(void);
int kc705_ddr_phy_debug(void);
#endif
#ifndef TINY3TPU_CPU_CLOCK_FREQUENCY
#define TINY3TPU_CPU_CLOCK_FREQUENCY CONFIG_CLOCK_FREQUENCY
#endif

static void uart_init(void)
{
    /* Synapse32 UART divisor is cycles per bit (not the usual 16550 x16). */
    const unsigned divisor = (TINY3TPU_CPU_CLOCK_FREQUENCY + 57600U) / 115200U;
    UART[3]=0x83; UART[0]=divisor&255; UART[1]=divisor>>8;
    UART[3]=3; UART[2]=7;
}
int putchar(int c)
{
    while (!(UART[5]&32)) { }
    UART[0]=(unsigned char)c;
    return (unsigned char)c;
}
int puts(const char *s)
{
    while (*s) putchar(*s++);
    putchar('\n'); return 0;
}
static int print_number(uint32_t n, unsigned base, unsigned width, int pad)
{
    char digits[32]; unsigned count=0; int written=0;
    do { unsigned digit=n%base; digits[count++]=(char)(digit<10?'0'+digit:'a'+digit-10); n/=base; } while(n);
    while(width>count) { putchar(pad); --width; ++written; }
    while(count) { putchar(digits[--count]); ++written; }
    return written;
}
/* Minimal integer-only calibration logger: supports the formats used by the
 * pinned LiteDRAM library; not a replacement for a general C printf library. */
int printf(const char *format, ...)
{
    va_list ap; va_start(ap, format); int written=0;
    while(*format) {
        if(*format!='%') { putchar(*format++); ++written; continue; }
        ++format; unsigned width=0; int pad=' ';
        if(*format=='0') { pad='0'; ++format; }
        while(*format>='0' && *format<='9') width=width*10+(unsigned)(*format++-'0');
        bool wide=false; if(*format=='l') { wide=true; ++format; }
        char code=*format; if(!code) break; ++format;
        if(code=='s') { const char *s=va_arg(ap,const char *); while(*s) { putchar(*s++); ++written; } }
        else if(code=='c') { putchar(va_arg(ap,int)); ++written; }
        else if(code=='d' || code=='i') {
            int32_t v=wide?(int32_t)va_arg(ap,long):va_arg(ap,int);
            if(v<0) { putchar('-'); ++written; if(width) --width; }
            written+=print_number(v<0?0U-(uint32_t)v:(uint32_t)v,10,width,pad);
        } else if(code=='u' || code=='x' || code=='X') {
            uint32_t v=wide?(uint32_t)va_arg(ap,unsigned long):va_arg(ap,unsigned);
            written+=print_number(v,code=='u'?10:16,width,pad);
        } else { putchar(code); ++written; }
    }
    va_end(ap); return written;
}
void *memcpy(void *dest,const void *src,size_t n)
{
    unsigned char *d=dest; const unsigned char *s=src;
    for(size_t i=0;i<n;++i) d[i]=s[i];
    return dest;
}
int abs(int x) { return x<0?-x:x; }

int memtest(unsigned int *address, unsigned long maxsize)
{
#ifdef TINY3TPU_DDR_PHY_ONLY
    (void)address; (void)maxsize;
    puts("PHY-only diagnostic: native DDR memory test disabled");
    return 0;
#else
    if((uintptr_t)address!=UINT32_C(0x40000000) || maxsize<16384) return 0;
    int ok=synapse32_dram_selftest();
    puts(ok?"DDR sparse-address / pattern / byte-mask test PASS":"DDR memory test FAIL");
#ifdef TINY3TPU_DDR_STRESS
    if (ok) ok = kc705_ddr_stress();
#endif
    return ok;
#endif
}
void memspeed(unsigned int *address,unsigned long size,bool read_only,bool random)
{
    (void)address;(void)size;(void)read_only;(void)random;
    puts("DDR throughput not measured by this bring-up image.");
}
int synapse32_dram_initialize(void)
{
    uart_init(); puts("tiny3tpu: DDR initialization (open-source LiteDRAM)");
#ifdef TINY3TPU_DDR_DEBUG
    if (!kc705_ddr_csr_check()) return 0;
#endif
    int ok = sdram_init();
#ifdef TINY3TPU_DDR_DEBUG
    if (!ok && kc705_ddr_phy_debug()) {
        ok=memtest((unsigned int *)(uintptr_t)UINT32_C(0x40000000),16384);
#ifdef CSR_DDRCTRL_BASE
        ddrctrl_init_error_write(!ok);
        ddrctrl_init_done_write(1);
#endif
    }
#endif
    return ok;
}
int synapse32_board_finish(int result)
{
    puts(result?"FAIL: DDR/TPU bring-up":"PASS: DDR-backed signed TPU GEMM");
    while (!(UART[5]&64)) { }
    return result;
}
