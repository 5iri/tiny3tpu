/* Resident mesh, host-controlled camera, binary UART responses; no DDR. */
#include "tiny3tpu_axis_mailbox.h"
#define BANANA_VERTICES 28U
static int8_t banana_vertices[BANANA_VERTICES*3];
#include <stddef.h>
#include <stdint.h>

#define UART ((volatile uint32_t *)(uintptr_t)0x20000000U)
static int8_t weights[9];
static int32_t bias[3], result[BANANA_VERTICES * 3];

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
static unsigned get_byte(void)
{
    while (!(UART[5] & 1)) {}
    return UART[0] & 255U;
}
static void put_byte(unsigned value)
{
    while (!(UART[5] & 32)) {}
    UART[0] = value & 255U;
}
static uint32_t get_word(void)
{
    uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) value |= get_byte() << (8 * i);
    return value;
}
static void put_word(uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) put_byte(value >> (8 * i));
}
static uint32_t cycle_count(void)
{
    return *(volatile uint32_t *)(uintptr_t)0x20002008U;
}
static uint32_t pack_row(const int8_t *values, unsigned count)
{
    uint32_t packed = 0;
    for (unsigned col = 0; col < count; ++col)
        packed |= (uint32_t)(uint8_t)values[col] << (8 * col);
    return packed;
}
/* This fixed 3x3 transform uses the two cores for different vertex rows.
 * Packed writes load four signed operands in one mailbox transaction.
 * B remains resident across all 26 eight-vertex batches in the frame. */
static int transform(tiny3tpu_axis_mailbox *mailbox)
{
    for (unsigned core = 0; core < 2; ++core)
        for (unsigned row = 0; row < 4; ++row)
            if (tiny3tpu_axis_mailbox_write32(mailbox, 0x50 + core * 32 + row * 4,
                    row < 3 ? pack_row(weights + row * 3, 3) : 0)) return -1;
    for (unsigned base = 0; base < BANANA_VERTICES; base += 8) {
        for (unsigned core = 0; core < 2; ++core)
            for (unsigned row = 0; row < 4; ++row) {
                unsigned vertex = base + core * 4 + row;
                if (tiny3tpu_axis_mailbox_write32(mailbox, 0x40 + core * 32 + row * 4,
                        vertex < BANANA_VERTICES ? pack_row(banana_vertices + vertex * 3, 3) : 0))
                    return -1;
            }
        if (tiny3tpu_axis_mailbox_write32(mailbox, 0, 1)) return -1;
        uint32_t status = 0;
        unsigned poll;
        for (poll = 0; poll < 1000; ++poll) {
            if (tiny3tpu_axis_mailbox_read32(mailbox, 16, &status)) return -1;
            if (status & 2) break;
        }
        if (poll == 1000) return -1;
        for (unsigned core = 0; core < 2; ++core)
            for (unsigned row = 0; row < 4; ++row) {
                unsigned vertex = base + core * 4 + row;
                if (vertex >= BANANA_VERTICES) continue;
                for (unsigned col = 0; col < 3; ++col) {
                    uint32_t value;
                    if (tiny3tpu_axis_mailbox_write32(mailbox, 12,
                            (core << 8) | (row << 16) | (col << 24)) ||
                        tiny3tpu_axis_mailbox_write32(mailbox, 0, 4) ||
                        tiny3tpu_axis_mailbox_read32(mailbox, 20, &value)) return -1;
                    result[vertex * 3 + col] = (int32_t)value + bias[col];
                }
            }
    }
    return 0;
}
int main(void)
{
    tiny3tpu_axis_mailbox mailbox;
    UART[3] = 0x83;
    UART[0] = 108;
    UART[1] = 0;
    UART[3] = 3;
    UART[2] = 7;
    if (tiny3tpu_axis_mailbox_init(&mailbox, NULL, read32, write32, 1000)) return 1;
    const char *banner = "CLOTH TRANSFORM 100MHz 921600 noddr\n";
    while (*banner) put_byte((unsigned char)*banner++);
    for (;;) {
        /* Resynchronize after connection/reset without interpreting text as a command. */
        uint32_t sync = 0;
        while (sync != 0x31514c43U) sync = (sync >> 8) | (get_byte() << 24);
        uint32_t sequence = get_word();
        for (unsigned i = 0; i < 9; ++i) weights[i] = (int8_t)get_byte();
        for (unsigned i = 0; i < 3; ++i) bias[i] = (int32_t)get_word();
        for(unsigned i=0;i<BANANA_VERTICES*3;i++) banana_vertices[i]=(int8_t)get_byte();
        uint32_t start = cycle_count();
        int status = transform(&mailbox);
        uint32_t elapsed = cycle_count() - start;
        uint32_t checksum = 0;
        if (!status) for (unsigned i = 0; i < BANANA_VERTICES * 3; ++i) checksum ^= (uint32_t)result[i];
        put_word(0x31524c43U);
        put_word(sequence);
        put_word((uint32_t)status);
        put_word(elapsed);
        put_word(status ? 0 : BANANA_VERTICES);
        put_word(checksum);
        if (!status) for (unsigned i = 0; i < BANANA_VERTICES * 3; ++i) put_word((uint32_t)result[i]);
    }
}
