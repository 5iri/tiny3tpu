#include <stdint.h>

/* Destructive bring-up test: run before loading model/data into DDR.
 * Touches the first 16 KiB and sparse address-line probes across the 1 GiB
 * window. This is not an exhaustive capacity or long-duration retention test.
 */
int synapse32_dram_selftest(void)
{
    volatile uint32_t *const ram = (volatile uint32_t *)(uintptr_t)UINT32_C(0x40000000);
    ram[0] = UINT32_C(0x55aa55aa);
    for (unsigned bit=0; bit<28; ++bit) ram[1U<<bit] = UINT32_C(0x10203040) ^ bit;
    if (ram[0] != UINT32_C(0x55aa55aa)) return 0;
    for (unsigned bit=0; bit<28; ++bit)
        if (ram[1U<<bit] != (UINT32_C(0x10203040) ^ bit)) return 0;
    for (unsigned invert=0; invert<2; ++invert) {
        for (unsigned i=0; i<4096; ++i)
            ram[i] = (UINT32_C(0x9e3779b9) * (i+1)) ^ (invert ? UINT32_MAX : 0);
        for (unsigned i=0; i<4096; ++i)
            if (ram[i] != ((UINT32_C(0x9e3779b9) * (i+1)) ^ (invert ? UINT32_MAX : 0))) return 0;
    }
    /* All eight byte lanes of a 64-bit physical data word, through 32-bit bus. */
    volatile uint8_t *const bytes = (volatile uint8_t *)ram;
    ram[0]=0; ram[1]=0;
    for (unsigned lane=0; lane<8; ++lane) bytes[lane]=(uint8_t)(0x81U+lane);
    if (ram[0]!=UINT32_C(0x84838281) || ram[1]!=UINT32_C(0x88878685)) return 0;
    volatile uint16_t *const halves = (volatile uint16_t *)ram;
    halves[1]=UINT16_C(0xfedc); halves[3]=UINT16_C(0xabcd);
    if (ram[0]!=UINT32_C(0xfedc8281) || ram[1]!=UINT32_C(0xabcd8685)) return 0;
    return 1;
}
