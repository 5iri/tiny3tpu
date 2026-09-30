/* First banana camera batch on the 100 MHz VexRiscv no-DDR SoC. */
#include "tiny3tpu_axis_mailbox.h"
#include "banana_fixture.h"
#include <stddef.h>
#include <stdint.h>

static int32_t result[96];

void *memset(void *dest, int value, size_t size)
{
    unsigned char *p = dest;
    for (size_t i = 0; i < size; ++i) p[i] = (unsigned char)value;
    return dest;
}

static int read32(void *user, uint32_t offset, uint32_t *value)
{
    (void)user;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    *value = *(volatile uint32_t *)(uintptr_t)(0x20001000U + offset);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    return 0;
}

static int write32(void *user, uint32_t offset, uint32_t value)
{
    (void)user;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    *(volatile uint32_t *)(uintptr_t)(0x20001000U + offset) = value;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    return 0;
}

int main(void)
{
    tiny3tpu_axis_mailbox mailbox;
    tiny3tpu_mmio io = {&mailbox, tiny3tpu_axis_mailbox_read32,
                       tiny3tpu_axis_mailbox_write32, 1000};
    if (tiny3tpu_axis_mailbox_init(&mailbox, NULL, read32, write32, 1000) ||
        tiny3tpu_mmio_qgemm(&io, banana_input, banana_weights, result, 32, 3, 3)) return 1;
    for (unsigned i = 0; i < 96; ++i) {
        result[i] += banana_bias[i % 3];
        if (result[i] != banana_expected[i]) return 2;
        *(volatile uint32_t *)(uintptr_t)0x20002004U = (uint32_t)result[i];
    }
    return 0;
}
