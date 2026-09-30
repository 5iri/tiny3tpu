#include "tiny3tpu_axis_mailbox.h"
#include "tiny3tpu_mmio_backend.h"
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* DDR-free KC705 bring-up firmware: UART banner plus the portable 5x11x7
 * signed TPU GEMM self-test through the AXI-Stream mailbox. Model upload
 * and inference arrive separately; this image proves clock/reset/UART/CPU/
 * sequencer/TPU on hardware. Exit code (via start.S -> 0x20002000 LEDs):
 * 0 PASS, otherwise the failing step. UART runs at 115200 baud. */

#define UART ((volatile uint32_t *)(uintptr_t)UINT32_C(0x20000000))
#ifndef CONFIG_CLOCK_FREQUENCY
#define CONFIG_CLOCK_FREQUENCY 40000000UL
#endif

static void uart_init(void)
{
    /* Synapse32 UART divisor is cycles per bit (not the usual 16550 x16). */
    const unsigned divisor = (CONFIG_CLOCK_FREQUENCY + 57600U) / 115200U;
    UART[3] = 0x83;
    UART[0] = divisor & 255U;
    UART[1] = (divisor >> 8) & 255U;
    UART[3] = 3;
    UART[2] = 7;
}

int putchar(int c)
{
    while (!(UART[5] & 32)) {
    }
    UART[0] = (unsigned char)c;
    return (unsigned char)c;
}

static int print_number(uint32_t n, unsigned base)
{
    char digits[32];
    unsigned count = 0;
    int written = 0;
    do {
        unsigned digit = n % base;
        digits[count++] = (char)(digit < 10 ? '0' + digit : 'a' + digit - 10);
        n /= base;
    } while (n);
    while (count) {
        putchar(digits[--count]);
        ++written;
    }
    return written;
}

/* Minimal integer-only logger: %s %c %d %u %x. */
int printf(const char *format, ...)
{
    va_list ap;
    va_start(ap, format);
    int written = 0;
    while (*format) {
        if (*format != '%') {
            putchar(*format++);
            ++written;
            continue;
        }
        ++format;
        char code = *format;
        if (!code) break;
        ++format;
        if (code == 's') {
            const char *s = va_arg(ap, const char *);
            while (*s) {
                putchar(*s++);
                ++written;
            }
        } else if (code == 'c') {
            putchar(va_arg(ap, int));
            ++written;
        } else if (code == 'd' || code == 'i') {
            int v = va_arg(ap, int);
            if (v < 0) {
                putchar('-');
                ++written;
            }
            written += print_number(v < 0 ? 0U - (uint32_t)v : (uint32_t)v, 10);
        } else if (code == 'u' || code == 'x') {
            written += print_number(va_arg(ap, unsigned), code == 'u' ? 10 : 16);
        } else {
            putchar(code);
            ++written;
        }
    }
    va_end(ap);
    return written;
}

/* Bare-metal test firmware. Only aligned LW/SW access the device window. */
static int local_read(void *user, uint32_t offset, uint32_t *value)
{
    (void)user;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    *value = *(volatile uint32_t *)(uintptr_t)(UINT32_C(0x20001000) + offset);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    return 0;
}

static int local_write(void *user, uint32_t offset, uint32_t value)
{
    (void)user;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    *(volatile uint32_t *)(uintptr_t)(UINT32_C(0x20001000) + offset) = value;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    return 0;
}

/* Freestanding helper; the compiler's RV32I libgcc supplies arithmetic. */
void *memset(void *dest, int value, size_t size)
{
    unsigned char *p = dest;
    for (size_t i = 0; i < size; ++i) p[i] = (unsigned char)value;
    return dest;
}

static int8_t a[5 * 11];
static int8_t b[11 * 7];
static int32_t result[5 * 7];

int main(void)
{
    tiny3tpu_axis_mailbox mailbox;
    tiny3tpu_mmio io = {&mailbox, tiny3tpu_axis_mailbox_read32,
                        tiny3tpu_axis_mailbox_write32, 1000};
    uint32_t value;

    uart_init();
    printf("tiny3tpu noddr bringup: UART alive\n");
    if (tiny3tpu_axis_mailbox_init(&mailbox, NULL, local_read, local_write, 1000)) {
        printf("FAIL mailbox init\n");
        return 1;
    }
    /* A bad register access must fail without poisoning the mailbox. */
    if (!io.read32(io.user, 0xfc, &value)) {
        printf("FAIL bad access accepted\n");
        return 2;
    }
    if (tiny3tpu_axis_mailbox_is_poisoned(&mailbox)) {
        printf("FAIL mailbox poisoned\n");
        return 3;
    }
    printf("mailbox OK\n");
    for (unsigned i = 0; i < 5 * 11; ++i) a[i] = (int)(i % 17) - 8;
    for (unsigned i = 0; i < 11 * 7; ++i) b[i] = (int)(i % 13) - 6;
    if (tiny3tpu_mmio_qgemm(&io, a, b, result, 5, 11, 7)) {
        printf("FAIL gemm launch\n");
        return 4;
    }
    for (unsigned row = 0; row < 5; ++row) {
        for (unsigned col = 0; col < 7; ++col) {
            int32_t expected = 0;
            for (unsigned inner = 0; inner < 11; ++inner)
                expected += a[row * 11 + inner] * b[inner * 7 + col];
            if (result[row * 7 + col] != expected) {
                printf("FAIL result [%u][%u] got %d want %d\n", row, col,
                       result[row * 7 + col], expected);
                return 5;
            }
            /* Report port also drives the sim scoreboard; harmless on board. */
            *(volatile uint32_t *)(uintptr_t)UINT32_C(0x20002004) =
                (uint32_t)result[row * 7 + col];
        }
    }
    printf("GEMM 5x11x7 PASS\n");
    printf("SELFTEST PASS\n");
    return 0;
}
