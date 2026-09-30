#include "tiny3tpu_axis_mailbox.h"
#include <stddef.h>

/* Bare-metal test firmware. Only aligned LW/SW access the device window. */
static int local_read(void *user, uint32_t offset, uint32_t *value)
{
    (void)user;
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
    *value = *(volatile uint32_t *)(uintptr_t)(UINT32_C(0x20001000) + offset);
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
    return 0;
}
static int local_write(void *user, uint32_t offset, uint32_t value)
{
    (void)user;
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
    *(volatile uint32_t *)(uintptr_t)(UINT32_C(0x20001000) + offset) = value;
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
    return 0;
}

/* Freestanding helper; the compiler's RV32I libgcc supplies arithmetic. */
void *memset(void *dest, int value, size_t size)
{
    unsigned char *p = dest;
    for (size_t i = 0; i < size; ++i) p[i] = (unsigned char)value;
    return dest;
}

#ifdef TINY3TPU_DRAM_SMOKE
static int8_t *const a = (int8_t *)(uintptr_t)UINT32_C(0x40010000);
static int8_t *const b = (int8_t *)(uintptr_t)UINT32_C(0x40011000);
static int32_t *const result = (int32_t *)(uintptr_t)UINT32_C(0x40012000);
int synapse32_dram_selftest(void);
#else
static int8_t a[5 * 11], b[11 * 7];
static int32_t result[5 * 7];
#endif
#ifdef TINY3TPU_DDR_CALIBRATION
int synapse32_dram_initialize(void);
#endif

int main(void)
{
    tiny3tpu_axis_mailbox mailbox;
    tiny3tpu_mmio io = {&mailbox, tiny3tpu_axis_mailbox_read32,
                        tiny3tpu_axis_mailbox_write32, 1000};
    uint32_t value;
#ifdef TINY3TPU_DDR_CALIBRATION
    if (!synapse32_dram_initialize()) return 10;
#endif
#ifdef TINY3TPU_DRAM_SMOKE
    if (!synapse32_dram_selftest()) return 11;
#endif
    if (tiny3tpu_axis_mailbox_init(&mailbox, NULL, local_read, local_write, 1000)) return 1;
    /* Error propagation must not poison a successfully retired transaction. */
    if (!io.read32(io.user, 0xfc, &value)) return 2;
    if (tiny3tpu_axis_mailbox_is_poisoned(&mailbox)) return 3;
    for (unsigned i = 0; i < 5 * 11; ++i) a[i] = (int)(i % 17) - 8;
    for (unsigned i = 0; i < 11 * 7; ++i) b[i] = (int)(i % 13) - 6;
    if (tiny3tpu_mmio_qgemm(&io, a, b, result, 5, 11, 7)) return 4;
    for (unsigned row = 0; row < 5; ++row) {
        for (unsigned col = 0; col < 7; ++col) {
            int32_t expected = 0;
            for (unsigned inner = 0; inner < 11; ++inner)
                expected += a[row * 11 + inner] * b[inner * 7 + col];
            if (result[row * 7 + col] != expected) return 5;
            /* Independent host scoreboard, simulation-only output port. */
            *(volatile uint32_t *)(uintptr_t)UINT32_C(0x20002004) =
                (uint32_t)result[row * 7 + col];
        }
    }
    return 0;
}
