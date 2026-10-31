#include "tiny3tpu_mmio_backend.h"
#include <stdio.h>
#include <string.h>

typedef struct device {
    int8_t a[8][4][4], b[8][4][4];
    int32_t c[8][4][4];
    uint32_t cfg, data, read_cfg, result;
    unsigned pending, starts, continue_starts, accesses, fail_at;
    unsigned weight_writes, result_reads, result_transactions, direct_result_reads;
    int stuck, instant, corrupt_high, accum_cap, result_window, sticky_early;
} device;

static int32_t signed_from_bits(uint32_t bits)
{
    return bits <= INT32_MAX ? (int32_t)bits :
           (int32_t)((int64_t)bits - INT64_C(4294967296));
}

static unsigned packed_mask_for_offset(uint32_t off, int *select_b)
{
    static const unsigned group_masks[12] = {
        0xffU, 0xffU, 0x0fU, 0xf0U, 0x11U, 0x22U,
        0x44U, 0x88U, 0x03U, 0x0cU, 0x30U, 0xc0U
    };
    if (off < 0x40U) {
        *select_b = 1;
        return (off & 0x10U) ? 0xaaU : 0x55U;
    }
    if (off < 0x140U) {
        unsigned core = (off - 0x40U) / 32U;
        *select_b = ((off >> 4) & 1U) != 0U;
        return 1U << core;
    }
    {
        unsigned group = (off - 0x140U) / 16U;
        *select_b = (group == 1U || (group >= 4U && group <= 7U));
        return group < 12U ? group_masks[group] : 0U;
    }
}

static int write32(void *user, uint32_t off, uint32_t value)
{
    device *d = user;
    unsigned core, row, col, k;
    if (++d->accesses == d->fail_at) return -1;
    if (off >= 0x20U && off < 0x200U && off % 4U == 0U) {
        int select_b = 0;
        unsigned mask = packed_mask_for_offset(off, &select_b);
        row = (off >> 2) & 3U;
        for (core = 0; core < 8U; ++core) {
            if (!(mask & (1U << core))) continue;
            for (col = 0; col < 4U; ++col) {
                int8_t byte = (int8_t)(value >> (8U * col));
                if (select_b) d->b[core][row][col] = byte;
                else d->a[core][row][col] = byte;
            }
        }
        if (select_b) ++d->weight_writes;
    } else if (off == 4) d->cfg = value;
    else if (off == 8) d->data = value;
    else if (off == 12) { d->read_cfg = value; ++d->result_transactions; }
    else if (off == 0 && (value == TINY3TPU_MMIO_CTRL_START ||
                          value == TINY3TPU_MMIO_CTRL_START_CONTINUE)) {
        const int continuing = value == TINY3TPU_MMIO_CTRL_START_CONTINUE;
        if (continuing && !d->accum_cap) return -1;
        ++d->starts;
        if (continuing) ++d->continue_starts;
        d->pending = 2;
        for (core = 0; core < 8; ++core)
            for (row = 0; row < 4; ++row)
                for (col = 0; col < 4; ++col) {
                    int32_t tile = 0;
                    for (k = 0; k < 4; ++k)
                        tile += d->a[core][row][k] * d->b[core][k][col];
                    if (!continuing) d->c[core][row][col] = 0;
                    d->c[core][row][col] = signed_from_bits(
                        (uint32_t)d->c[core][row][col] + (uint32_t)tile);
                }
    } else if (off == 0 && value == 2) {
        core = (d->cfg >> 8) & 7U; row = (d->cfg >> 16) & 3U;
        col = (d->cfg >> 24) & 3U;
        if (d->cfg & 1U) d->b[core][row][col] = (int8_t)d->data;
        else d->a[core][row][col] = (int8_t)d->data;
    } else if (off == 0 && value == 4) {
        ++d->result_transactions;
        d->result = (uint32_t)d->c[(d->read_cfg >> 8) & 7U]
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
        uint32_t caps = (d->accum_cap ? TINY3TPU_MMIO_STATUS_ACCUM_CAP : 0U) |
                        (d->result_window ? TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP : 0U);
        if (d->sticky_early && d->starts) { *value=2U|caps; return 0; }
        if (d->instant && d->starts) { *value = 2U | caps; return 0; }
        *value = (d->pending != 0U ? 1U : 0U) | caps;
        if (d->pending && !d->stuck) --d->pending;
    } else if (off == 20) {
        *value = d->result;
        ++d->result_reads;
        ++d->result_transactions;
    } else if (off == 24) {
        *value = (d->result & UINT32_C(0x80000000) ? UINT32_MAX : 0) ^
                 (d->corrupt_high ? 1U : 0U);
        ++d->result_reads;
        ++d->result_transactions;
    } else if (off >= 0x200U && off < 0x400U && (off & 3U) == 0U) {
        unsigned core, row, col;
        if (!d->result_window || d->pending != 0U) return -1;
        core=(off-0x200U)/64U; row=((off-0x200U)%64U)/16U;
        col=((off-0x200U)%16U)/4U;
        *value=(uint32_t)d->c[core][row][col];
        ++d->result_reads;
        ++d->direct_result_reads;
        ++d->result_transactions;
    } else return -1;
    return 0;
}

static void fill_inputs(int8_t *a, int8_t *b, unsigned m, unsigned k, unsigned n)
{
    unsigned i;
    for (i = 0; i < m*k; ++i) a[i] = (int8_t)((int)(i%17U)-8);
    for (i = 0; i < k*n; ++i) b[i] = (int8_t)((int)(i%13U)-6);
}

static int check_result(const int8_t *a, const int8_t *b, const int32_t *out,
                        unsigned m, unsigned k, unsigned n)
{
    unsigned i, j, t;
    for (i = 0; i < m; ++i) for (j = 0; j < n; ++j) {
        int64_t expected = 0;
        for (t = 0; t < k; ++t) expected += (int32_t)a[i*k+t] * b[t*n+j];
        if (expected < INT32_MIN || expected > INT32_MAX || out[i*n+j] != expected)
            return -1;
    }
    return 0;
}

static void pack_operands(const int8_t *a, const int8_t *b,
                          uint32_t *packed_a, uint32_t *packed_b,
                          unsigned m, unsigned k, unsigned n)
{
    unsigned rt=(m+3U)/4U, ct=(n+3U)/4U, kt=(k+3U)/4U;
    unsigned r,t,c;
    memset(packed_a,0,(size_t)rt*kt*4U*sizeof(*packed_a));
    memset(packed_b,0,(size_t)ct*kt*4U*sizeof(*packed_b));
    for (r=0;r<m;++r) for (t=0;t<k;++t) {
        size_t wi=((size_t)(r/4U)*kt+t/4U)*4U+r%4U;
        packed_a[wi] |= (uint32_t)(uint8_t)a[(size_t)r*k+t] << (8U*(t%4U));
    }
    for (c=0;c<n;++c) for (t=0;t<k;++t) {
        size_t wi=((size_t)(c/4U)*kt+t/4U)*4U+t%4U;
        packed_b[wi] |= (uint32_t)(uint8_t)b[(size_t)t*n+c] << (8U*(c%4U));
    }
}

static int packed_case(unsigned m, unsigned k, unsigned n, int accum_cap,
                       int result_window, unsigned pack_mode)
{
    device d={0}; tiny3tpu_mmio io={&d,read32,write32,10};
    int8_t a[8*20],b[20*16]; int32_t out[8*16];
    uint32_t pa[((8U+3U)/4U)*((20U+3U)/4U)*4U];
    uint32_t pb[((16U+3U)/4U)*((20U+3U)/4U)*4U];
    if (m > 8 || k > 20 || n > 16) return -1;
    fill_inputs(a,b,m,k,n);
    pack_operands(a,b,pa,pb,m,k,n);
    d.accum_cap=accum_cap; d.result_window=result_window;
    if (tiny3tpu_mmio_qgemm_packed(&io,
            (pack_mode&1U)?NULL:a,(pack_mode&2U)?NULL:b,
            (pack_mode&1U)?pa:NULL,(pack_mode&2U)?pb:NULL,out,m,k,n) ||
        check_result(a,b,out,m,k,n)) return -1;
    return 0;
}

static int run_case(unsigned m, unsigned k, unsigned n, int accum_cap, int result_window,
                    unsigned expected_result_reads, unsigned expected_transactions,
                    unsigned *starts,
                    unsigned *continued)
{
    device d = {0};
    tiny3tpu_mmio io = {&d, read32, write32, 10};
    int8_t a[16 * 64], b[64 * 8];
    int32_t out[16 * 8];
    if (m > 16 || k > 64 || n > 8) return -1;
    fill_inputs(a,b,m,k,n);
    d.accum_cap = accum_cap;
    d.result_window = result_window;
    if (tiny3tpu_mmio_qgemm(&io,a,b,out,m,k,n) ||
        check_result(a,b,out,m,k,n) || d.result_reads != expected_result_reads ||
        d.result_transactions != expected_transactions ||
        (result_window && d.direct_result_reads != expected_result_reads)) {
        fprintf(stderr,"case m%u k%u n%u caps%d/%d reads%u/%u direct%u tx%u/%u\n",
                m,k,n,accum_cap,result_window,d.result_reads,expected_result_reads,
                d.direct_result_reads,d.result_transactions,expected_transactions);
        return -1;
    }
    if (starts) *starts=d.starts;
    if (continued) *continued=d.continue_starts;
    return 0;
}

int main(void)
{
    device d = {0};
    tiny3tpu_mmio io = {&d, read32, write32, 10};
    int8_t a[5 * 11], b[11 * 7];
    int32_t out[5 * 7];
    unsigned i, k, failure, total_accesses, starts, continued;
    fill_inputs(a,b,5,11,7);
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) ||
        check_result(a,b,out,5,11,7)) return 1;
    if (d.starts != 3) return 2;
    total_accesses = d.accesses;
    memset(&d, 0, sizeof(d)); d.instant = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7)) return 3;
    for (failure = 1; failure <= total_accesses; ++failure) {
        memset(&d, 0, sizeof(d)); d.fail_at = failure;
        if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) == 0) return 4;
    }
    memset(&d, 0, sizeof(d)); d.stuck = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) == 0) return 5;
    memset(&d, 0, sizeof(d)); d.pending = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) == 0 || d.starts != 0) return 6;
    memset(&d, 0, sizeof(d)); d.corrupt_high = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) == 0) return 7;
    memset(&d, 0, sizeof(d)); d.accum_cap = 1;
    if (tiny3tpu_mmio_qgemm(&io, a, b, out, 5, 11, 7) ||
        check_result(a,b,out,5,11,7)) return 22;
    total_accesses=d.accesses;
    for (failure=1; failure<=total_accesses; ++failure) {
        memset(&d,0,sizeof(d)); d.accum_cap=1; d.fail_at=failure;
        if (tiny3tpu_mmio_qgemm(&io,a,b,out,5,11,7)==0) return 23;
    }
    memset(&d,0,sizeof(d)); d.accum_cap=1; d.stuck=1;
    if (tiny3tpu_mmio_qgemm(&io,a,b,out,5,11,7)==0) return 24;
    memset(&d,0,sizeof(d)); d.accum_cap=1; d.corrupt_high=1;
    if (tiny3tpu_mmio_qgemm(&io,a,b,out,5,11,7)==0) return 25;

    /* Short K remains one clear/start with the same result transaction count. */
    int8_t short_a[28*3], short_b[3*3];
    int32_t short_out[28*3], short_out_legacy[28*3];
    memset(short_a, -128, sizeof(short_a)); memset(short_b, 127, sizeof(short_b));
    memset(&d, 0, sizeof(d)); d.accum_cap = 1;
    if (tiny3tpu_mmio_qgemm(&io, short_a, short_b, short_out, 28, 3, 3)) return 8;
    for (i=0; i<28*3; ++i) if (short_out[i] != -48768) return 9;
    if (d.starts != 1 || d.continue_starts != 0 || d.weight_writes != 4 ||
        d.result_reads != 28*3*2 || d.result_transactions != 28*3*4 ||
        d.accesses >= 500) return 10;
    memcpy(short_out_legacy,short_out,sizeof(short_out));
    memset(&d,0,sizeof(d));
    if (tiny3tpu_mmio_qgemm(&io,short_a,short_b,short_out,28,3,3) ||
        memcmp(short_out,short_out_legacy,sizeof(short_out)) || d.starts != 1U ||
        d.result_reads != 28U*3U*2U || d.result_transactions != 28U*3U*4U) return 21;
    /* Per-call state is reset even when hardware supports retained sums. */
    d.accum_cap=1;
    memset(short_b, -128, sizeof(short_b));
    if (tiny3tpu_mmio_qgemm(&io, short_a, short_b, short_out, 28, 3, 3)) return 11;
    for (i=0; i<28*3; ++i) if (short_out[i] != 49152) return 12;

    /* Exercise accumulator continuation and short final K tails in both
     * 2D grid and K-parallel schedules. */
    for (k=9; k<=17; k+=8) {
        if (run_case(16,k,5,1,0,16U*5U*2U,16U*5U*4U,&starts,&continued) ||
            starts != (k+3U)/4U || continued != starts-1U) return 13;
        if (run_case(3,k+32,3,1,0,3U*3U*8U*2U,3U*3U*8U*4U,&starts,&continued) ||
            starts != (k+32U+31U)/32U || continued != starts-1U) return 14;
        if (run_case(16,k,5,0,0,16U*5U*((k+3U)/4U)*2U,
                     16U*5U*((k+3U)/4U)*4U,&starts,&continued) ||
            continued != 0U) return 15;
    }

    /* Single-image 784x10 classifier: 80 partial values (eight K-split cores),
     * each with one CFG, CTRL, low and high transaction. */
    {
        static int8_t ca[784], cb[784*10]; static int32_t co[10];
        device cd = {0}; tiny3tpu_mmio cio = {&cd,read32,write32,10};
        fill_inputs(ca,cb,1,784,10); cd.accum_cap=1;
        if (tiny3tpu_mmio_qgemm(&cio,ca,cb,co,1,784,10) ||
            check_result(ca,cb,co,1,784,10) || cd.result_reads != 160U ||
            cd.result_transactions != 320U) return 16;
        memset(&cd,0,sizeof(cd)); cd.accum_cap=1; cd.result_window=1;
        if (tiny3tpu_mmio_qgemm(&cio,ca,cb,co,1,784,10) ||
            check_result(ca,cb,co,1,784,10) || cd.direct_result_reads != 80U ||
            cd.result_transactions != 80U) return 35;
    }
    /* 8x8x8 attention: 512 MACs; 2x4 grid runs two K launches and reduces
     * 128 output partials to 64 final values. */
    if (run_case(8,8,8,1,0,8U*8U*2U,8U*8U*4U,&starts,&continued) ||
        starts != 2U || continued != 1U) return 17;
    if (run_case(8,8,8,1,1,8U*8U,8U*8U,&starts,&continued) ||
        starts != 2U || continued != 1U) {
        fprintf(stderr,"attention window counts: starts %u continue %u\n",starts,continued);
        return 36;
    }

    /* Both status capabilities are independent. The 8x9x5 shape uses the
     * 2x4 grid schedule: three launches, 40 outputs, and either 40 retained
     * results or 120 legacy per-K partials. */
    for (i=0;i<4U;++i) {
        const int accum=(i&1U)!=0U, window=(i&2U)!=0U;
        const unsigned values=40U*(accum?1U:3U);
        if (run_case(8,9,5,accum,window,values*(window?1U:2U),
                     values*(window?1U:4U),&starts,&continued) ||
            starts != 3U || continued != (accum?2U:0U)) {
            fprintf(stderr,"combo %u: starts %u continued %u\n",i,starts,continued);
            return 27;
        }
    }

    /* Packed constants have schedule-independent canonical words. Exercise
     * A-only, B-only, and both packed for all three schedules under
     * every independent status capability combination. */
    for (i=0;i<4U;++i) for (k=1;k<=3U;++k) {
        int accum=(i&1U)!=0U, window=(i&2U)!=0U;
        if (packed_case(8,9,5,accum,window,k) ||
            packed_case(3,9,3,accum,window,k) ||
            packed_case(3,9,5,accum,window,k) ||
            packed_case(1,3,9,accum,window,k) ||
            packed_case(5,7,13,accum,window,k)) return 28;
    }

    /* Short, wide products must use both cores in one launch; column tails
     * and retained K tails must neither alias nor include stale core outputs. */
    for (i=0;i<4U;++i) {
        const int accum=(i&1U)!=0U, window=(i&2U)!=0U;
        if (run_case(4,4,8,accum,window,32U*(window?1U:2U),
                     32U*(window?1U:4U),&starts,&continued) ||
            starts != 1U || continued != 0U) return 37;
        const unsigned values=15U*3U;
        if (run_case(3,9,5,accum,window,values*(window?1U:2U),
                     values*(window?1U:4U),&starts,&continued) ||
            starts != 2U || continued != 0U) return 38;
    }

    /* Result-window bus errors are surfaced even when no selector readback is
     * used; the device also rejects direct reads while a launch remains busy. */
    for (i=0;i<4U;++i) {
        memset(&d,0,sizeof(d)); d.result_window=1; d.accum_cap=(i&1U)!=0U;
        if (tiny3tpu_mmio_qgemm(&io,a,b,out,5,11,7)) return 29;
        total_accesses=d.accesses;
        for (failure=1;failure<=total_accesses;++failure) {
            memset(&d,0,sizeof(d)); d.result_window=1;
            d.accum_cap=(i&1U)!=0U; d.fail_at=failure;
            if (tiny3tpu_mmio_qgemm(&io,a,b,out,5,11,7)==0) return 30;
        }
        memset(&d,0,sizeof(d)); d.result_window=1;
        d.accum_cap=(i&1U)!=0U; d.stuck=1;
        if (tiny3tpu_mmio_qgemm(&io,a,b,out,5,11,7)==0) return 31;
    }
    memset(&d,0,sizeof(d)); d.result_window=1; d.sticky_early=1;
    if (tiny3tpu_mmio_qgemm(&io,a,b,out,5,11,7)==0) return 32;

    /* A call with K beyond the safe retained-accumulator bound must fall back
     * to per-launch host accumulation, preserving range checks and cancellation. */
    {
        static int8_t large_a[132105], large_b[132105]; int32_t scalar;
        device ld = {0}; tiny3tpu_mmio lio = {&ld,read32,write32,10};
        memset(large_a,-128,sizeof(large_a)); memset(large_b,-128,sizeof(large_b));
        ld.accum_cap=1;
        if (tiny3tpu_mmio_qgemm(&lio,large_a,large_b,&scalar,1,131071,1) ||
            scalar != INT32_C(2147467264)) return 26;
        memset(&ld,0,sizeof(ld)); ld.accum_cap=1; ld.result_window=1;
        if (tiny3tpu_mmio_qgemm(&lio,large_a,large_b,&scalar,1,131071,1) ||
            scalar != INT32_C(2147467264)) return 33;
        for (i=0;i<4U;++i) {
            memset(&ld,0,sizeof(ld)); ld.accum_cap=(i&1U)!=0U;
            ld.result_window=(i&2U)!=0U;
            if (tiny3tpu_mmio_qgemm(&lio,large_a,large_b,&scalar,1,131072,1)==0)
                return 18;
        }
        memset(&ld,0,sizeof(ld)); ld.accum_cap=1;
        memset(large_b,127,sizeof(large_b));
        int64_t negative_reference=0;
        for (i=0; i<132105U; ++i) negative_reference += (int32_t)large_a[i]*large_b[i];
        if (negative_reference >= INT32_MIN ||
            tiny3tpu_mmio_qgemm(&lio,large_a,large_b,&scalar,1,132105,1)==0) return 19;
        memset(&ld,0,sizeof(ld)); ld.accum_cap=1;
        for (i=0; i<65536U; ++i) large_b[i]=-128;
        for (; i<131072U; ++i) large_b[i]=127;
        int64_t cancellation_reference=0;
        for (i=0; i<131072U; ++i) cancellation_reference += (int32_t)large_a[i]*large_b[i];
        if (tiny3tpu_mmio_qgemm(&lio,large_a,large_b,&scalar,1,131072,1) ||
            cancellation_reference < INT32_MIN || cancellation_reference > INT32_MAX ||
            scalar != cancellation_reference) return 20;
    }

    puts("MMIO backend: retained accumulation, fallback overflow checks, bus errors and timeouts passed");
    return 0;
}
