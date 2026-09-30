#include <stdint.h>
#include <stdio.h>

/* Destructive bring-up test, before any application data is loaded.
 * Two MiB in eight windows spanning the 1 GiB DIMM; this is not a full-capacity
 * or retention qualification. VexRiscv Lite has no data cache.
 */
static volatile uint32_t *window(unsigned index)
{
    const uintptr_t address = index == 7 ? UINT32_C(0x7ffc0000) :
        UINT32_C(0x40000000) + index * UINT32_C(0x08000000);
    return (volatile uint32_t *)address;
}

static uint32_t pattern(uintptr_t address, unsigned round)
{
    uint32_t value = (uint32_t)address ^ (UINT32_C(0x9e3779b9) * (round + 1));
    value ^= value >> 16;
    value *= UINT32_C(0x85ebca6b);
    return value ^ (value >> 13);
}

static int mismatch(volatile uint32_t *address, uint32_t expected, uint32_t actual)
{
    printf("DDR stress FAIL at %08x: expected %08x got %08x\n",
           (unsigned)(uintptr_t)address, (unsigned)expected, (unsigned)actual);
    return 0;
}

int kc705_ddr_stress(void)
{
    const unsigned words = 65536;
    for (unsigned round = 0; round < 2; ++round) {
        printf("DDR stress round %u: writing 2 MiB across eight windows\n", round + 1);
        for (unsigned w = 0; w < 8; ++w) {
            volatile uint32_t *ram = window(w);
            for (unsigned i = 0; i < words; ++i)
                ram[i] = pattern((uintptr_t)&ram[i], round);
        }
        /* Fill every window before verification to expose cross-window aliasing.
         * Read backwards, check, then invert in place. */
        for (unsigned w = 8; w-- > 0;) {
            volatile uint32_t *ram = window(w);
            for (unsigned i = words; i-- > 0;) {
                uint32_t expected = pattern((uintptr_t)&ram[i], round);
                uint32_t actual = ram[i];
                if (actual != expected) return mismatch(&ram[i], expected, actual);
                ram[i] = ~expected;
            }
        }
        for (unsigned w = 0; w < 8; ++w) {
            volatile uint32_t *ram = window(w);
            for (unsigned i = 0; i < words; ++i) {
                uint32_t expected = ~pattern((uintptr_t)&ram[i], round);
                uint32_t actual = ram[i];
                if (actual != expected) return mismatch(&ram[i], expected, actual);
            }
        }
        printf("DDR stress round %u: pattern and inverse PASS\n", round + 1);
    }
    for (unsigned w = 0; w < 8; ++w) {
        volatile uint32_t *ram = window(w);
        volatile uint8_t *bytes = (volatile uint8_t *)ram;
        for (unsigned i = 0; i < 16; ++i) ram[i] = UINT32_C(0xaaaaaaaa);
        for (unsigned lane = 0; lane < 64; ++lane) {
            bytes[lane] = (uint8_t)(lane + 1);
            for (unsigned i = 0; i < 16; ++i) {
                uint32_t expected = 0;
                for (unsigned b = 0; b < 4; ++b) {
                    unsigned at = i * 4 + b;
                    expected |= (at <= lane ? at + 1 : 0xaaU) << (b * 8);
                }
                uint32_t actual = ram[i];
                if (actual != expected) return mismatch(&ram[i], expected, actual);
            }
        }
    }
    puts("DDR stress PASS: 2 MiB, two rounds, inverse patterns, all 64 byte positions");
    return 1;
}
