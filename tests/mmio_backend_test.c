#include "tiny3tpu_mmio_backend.h"
#include <stdio.h>
#include <string.h>

typedef struct device {
    int8_t a[2][4][4], b[2][4][4];
    int32_t c[2][4][4];
    uint32_t cfg, data, read_cfg, result;
    unsigned pending, starts, accesses, fail_at, weight_writes;
    int stuck, instant, corrupt_high;
} device;

static int write32(void *user, uint32_t off, uint32_t value)
{
    device *d = user;
    unsigned core, row, col, k;
    if (++d->accesses == d->fail_at) return -1;
    if (off >= 0x40 && off <= 0x7c && off % 4 == 0) {
        unsigned slot = (off-0x40)/4;
        core = slot/8; row = slot%4;
        for (col=0; col<4; ++col) {
            int8_t byte = (int8_t)(value >> (8*col));
            if (slot%8 >= 4) d->b[core][row][col] = byte;
            else d->a[core][row][col] = byte;
        }
        if (slot%8 >= 4) ++d->weight_writes;
    } else if (off == 4) d->cfg = value;
    else if (off == 8) d->data = value;
    else if (off == 12) d->read_cfg = value;
    else if (off == 0 && value == 2) {
        core = (d->cfg >> 8) & 1U; row = (d->cfg >> 16) & 3U;
        col = (d->cfg >> 24) & 3U;
        if (d->cfg & 1U) d->b[core][row][col] = (int8_t)d->data;
        else d->a[core][row][col] = (int8_t)d->data;
    } else if (off == 0 && value == 1) {
        ++d->starts; d->pending = 2;
        for (core = 0; core < 2; ++core)
            for (row = 0; row < 4; ++row)
                for (col = 0; col < 4; ++col) {
                    d->c[core][row][col] = 0;
                    for (k = 0; k < 4; ++k)
                        d->c[core][row][col] += d->a[core][row][k] * d->b[core][k][col];
                }
    } else if (off == 0 && value == 4) {
        d->result = (uint32_t)d->c[(d->read_cfg >> 8) & 1U]
                                       [(d->read_cfg >> 16) & 3U]
                                       [(d->read_cfg >> 24) & 3U];
    } else return -1;
    return 0;
}

static int read32(void *user, uint32_t off, uint32_t *value)
{
    device *d = user;
    if (++d->accesses == d->fail_at) return -1;
    if (off == 16) {
        if (d->instant && d->starts) { *value = 2U; return 0; }
        *value = d->pending != 0;
        if (d->pending && !d->stuck) --d->pending;
    } else if (off == 20) *value = d->result;
    else if (off == 24) *value = (d->result & UINT32_C(0x80000000) ? UINT32_MAX : 0) ^ (d->corrupt_high ? 1U : 0U);
    else return -1;
    return 0;
}

int main(void)
{
    device d = {0};
    tiny3tpu_mmio io = {&d, read32, write32, 10};
    int8_t a[5 * 11], b[11 * 7];
    int32_t out[5 * 7];
    unsigned i, j, k, failure;
    for (i = 0; i < sizeof(a); ++i) a[i] = (int8_t)((int)(i % 17) - 8);
    for (i = 0; i < sizeof(b); ++i) b[i] = (int8_t)((int)(i % 13) - 6);
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7)) return 1;
    for (i = 0; i < 5; ++i) for (j = 0; j < 7; ++j) {
        int32_t expected = 0;
        for (k = 0; k < 11; ++k) expected += a[i * 11 + k] * b[k * 7 + j];
        if (out[i * 7 + j] != expected) return 2;
    }
    if (d.starts != 6) return 3;
    unsigned total_accesses = d.accesses;
    memset(&d, 0, sizeof(d)); d.instant = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7)) return 7;
    for (failure = 1; failure <= total_accesses; ++failure) {
        memset(&d, 0, sizeof(d)); d.fail_at = failure;
        if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) == 0) return 4;
    }
    memset(&d, 0, sizeof(d)); d.stuck = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) == 0) return 5;
    memset(&d, 0, sizeof(d)); d.pending = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) == 0 || d.starts != 0) return 6;
    memset(&d, 0, sizeof(d)); d.corrupt_high = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) == 0) return 8;
    /* Short K must use both row cores and retain B across row batches. */
    int8_t short_a[28*3], short_b[3*3];int32_t short_out[28*3];
    memset(short_a, -128, sizeof(short_a));memset(short_b, 127, sizeof(short_b));
    memset(&d, 0, sizeof(d));
    if (tiny3tpu_mmio_qgemm(&io, short_a, short_b, short_out, 28, 3, 3)) return 9;
    for (i=0;i<28*3;i++)if (short_out[i] != -48768) return 10;
    if (d.starts != 4 || d.weight_writes != 8 || d.accesses >= 500) return 11;
    /* A new call must not reuse stale cached weights or operands. */
    memset(short_b, -128, sizeof(short_b));
    if (tiny3tpu_mmio_qgemm(&io, short_a, short_b, short_out, 28, 3, 3)) return 12;
    for (i=0;i<28*3;i++)if (short_out[i] != 49152) return 13;
    static int8_t large_a[131072], large_b[131072];int32_t scalar;
    memset(large_a,-128,sizeof(large_a));memset(large_b,-128,sizeof(large_b));
    memset(&d,0,sizeof(d));
    if (tiny3tpu_mmio_qgemm(&io,large_a,large_b,&scalar,1,131071,1) || scalar!=2147467264) return 14;
    if (tiny3tpu_mmio_qgemm(&io,large_a,large_b,&scalar,1,131072,1)==0) return 15;
    puts("MMIO backend: tiled signed matmul, tails, bus errors and timeouts passed");
    return 0;
}
