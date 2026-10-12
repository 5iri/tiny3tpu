#include "tiny3tpu_mmio_backend.h"

#include <limits.h>
#include <stddef.h>

enum { CTRL = 0, CRD_CFG = 12,
       STATUS = 16, RESULT_LO = 20, RESULT_HI = 24 };

/* A retained int32 accumulator is safe for every legal K through this limit,
 * including the row-parallel schedule where one core sees the full K. */
enum { ACCUMULATOR_SAFE_MAX_K = 131071U };

/* Cache only within this call: another caller or reset may change the device.
 * Full-word packed writes complete after all four byte stores are consumed. */
static int write_row(tiny3tpu_mmio *io, uint32_t cache[16], uint32_t *valid,
                     unsigned slot, uint32_t value)
{
    if ((*valid & (1U << slot)) && cache[slot] == value) return 0;
    if (io->write32(io->user, 0x40U + slot * 4U, value)) return -1;
    cache[slot] = value;
    *valid |= 1U << slot;
    return 0;
}

static int wait_done(tiny3tpu_mmio *io)
{
    uint32_t poll, status;
    int seen_busy = 0;
    for (poll = 0; poll < io->poll_limit; ++poll) {
        if (io->read32(io->user, STATUS, &status)) return -1;
        if (status & 2U) return 0; /* Sticky completion survives delayed polling. */
        if (status & 1U) seen_busy = 1;
        else if (seen_busy) return 0;
    }
    return -1;
}

/* Keep result handling out of the operand-loading loop's instruction-cache
 * footprint. Retained accumulation reads this only after the last K tile. */
#if defined(__GNUC__)
__attribute__((noinline))
#endif
static int read_tile(tiny3tpu_mmio *io, int window, unsigned core,
                     unsigned rows, unsigned cols, int64_t sums[4][4])
{
    for (unsigned row=0; row<rows; ++row) for (unsigned col=0; col<cols; ++col) {
        uint32_t lo;
        if (window) {
            if (io->read32(io->user,0x80U+core*64U+row*16U+col*4U,&lo)) return -1;
        } else {
            uint32_t hi;
            const uint32_t cfg=(core<<8)|(row<<16)|(col<<24);
            if (io->write32(io->user,CRD_CFG,cfg) || io->write32(io->user,CTRL,4U) ||
                io->read32(io->user,RESULT_LO,&lo) || io->read32(io->user,RESULT_HI,&hi)) return -1;
            if (hi != ((lo&UINT32_C(0x80000000)) ? UINT32_MAX : 0U)) return -1;
        }
        sums[row][col] += lo <= INT32_MAX ? (int64_t)lo : (int64_t)lo-INT64_C(4294967296);
    }
    return 0;
}

#if defined(__GNUC__)
__attribute__((always_inline))
#endif
static inline int qgemm_scheduled(void *user, const int8_t *a, const int8_t *b,
                      const uint32_t *packed_a, const uint32_t *packed_b,
                      int32_t *output, uint32_t m, uint32_t k, uint32_t n,
                      const int col_parallel)
{
    tiny3tpu_mmio *io = user;
    uint32_t row0, col0, inner0, status, cache[16], valid = 0;
    uint64_t ktile_count, a_words, b_words;
    if (io == NULL || io->read32 == NULL || io->write32 == NULL ||
        io->poll_limit == 0U || (a == NULL && packed_a == NULL) ||
        (b == NULL && packed_b == NULL) || output == NULL ||
        m == 0U || k == 0U || n == 0U ||
        (a != NULL && (uint64_t)m * k > SIZE_MAX) ||
        (b != NULL && (uint64_t)k * n > SIZE_MAX) ||
        (uint64_t)m * n > SIZE_MAX / sizeof(*output)) return -1;
    ktile_count=1U+((uint64_t)k-1U)/4U;
    a_words=(1U+((uint64_t)m-1U)/4U)*ktile_count*4U;
    b_words=(1U+((uint64_t)n-1U)/4U)*ktile_count*4U;
    if ((packed_a != NULL && a_words > SIZE_MAX / sizeof(*packed_a)) ||
        (packed_b != NULL && b_words > SIZE_MAX / sizeof(*packed_b))) return -1;
    if (io->read32(io->user, STATUS, &status) || (status & 1U)) return -1;
    const int retain_accum =
        (status & TINY3TPU_MMIO_STATUS_ACCUM_CAP) != 0U &&
        k <= ACCUMULATOR_SAFE_MAX_K;
    const int result_window =
        (status & TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP) != 0U;
    /* Choose the axis that needs fewer launches. Preserve row/K tie-breaking
     * so adding columns does not disturb operand reuse in existing schedules. */
    const uint64_t row_tiles = (uint64_t)(1U + (m-1U)/8U) *
                              (1U + (k-1U)/4U);
    const uint64_t k_tiles = (uint64_t)(1U + (m-1U)/4U) *
                            (1U + (k-1U)/8U);
    const int row_parallel = !col_parallel && row_tiles <= k_tiles;
    const int k_parallel = !col_parallel && !row_parallel;
    const uint32_t row_step = row_parallel ? 8U : 4U;
    const uint32_t k_step = k_parallel ? 8U : 4U;
    const uint32_t col_step = col_parallel ? 8U : 4U;
    for (col0 = 0; col0 < n;) {
        uint32_t cols = n-col0 < col_step ? n-col0 : col_step;
        for (row0 = 0; row0 < m;) {
            uint32_t rows = m-row0 < row_step ? m-row0 : row_step;
            int64_t sums[8][4] = {{0}};
            uint32_t row, col, core;
            for (inner0 = 0; inner0 < k;) {
                uint32_t inner = k-inner0 < k_step ? k-inner0 : k_step;
                for (core = 0; core < 2U; ++core) {
                    const uint32_t rbase = row_parallel ? core*4U : 0U;
                    const uint32_t kbase = k_parallel ? core*4U : 0U;
                    const uint32_t cbase = col_parallel ? core*4U : 0U;
                    for (row = 0; row < 4U; ++row) {
                        uint32_t ap = 0, bp = 0;
                        const uint32_t global_row = row0+rbase+row;
                        const uint32_t global_inner_base = inner0+kbase;
                        const int a_row_valid = rbase+row < rows;
                        if (packed_a != NULL && a_row_valid && kbase < inner) {
                            const size_t wi =
                                (((size_t)(global_row/4U)*(size_t)ktile_count +
                                  global_inner_base/4U)*4U + global_row%4U);
                            const uint32_t valid_lanes = inner-kbase < 4U ? inner-kbase : 4U;
                            ap = packed_a[wi];
                            if (valid_lanes < 4U)
                                ap &= (UINT32_C(1) << (8U*valid_lanes))-1U;
                        }
                        if (packed_b != NULL && kbase+row < inner && cbase < cols) {
                            const uint32_t global_inner = inner0+kbase+row;
                            const size_t wi =
                                (((size_t)((col0+cbase)/4U)*(size_t)ktile_count +
                                  global_inner/4U)*4U + global_inner%4U);
                            const uint32_t valid_cols = cols-cbase < 4U ? cols-cbase : 4U;
                            bp = packed_b[wi];
                            if (valid_cols < 4U)
                                bp &= (UINT32_C(1) << (8U*valid_cols))-1U;
                        }
                        if (packed_a == NULL && a_row_valid && kbase < inner) {
                            const int8_t *source=a+(size_t)global_row*k+inner0+kbase;
                            for (col=0; col<4U && kbase+col<inner; ++col)
                                ap |= (uint32_t)(uint8_t)source[col] << (8U*col);
                        }
                        if (packed_b == NULL && kbase+row < inner && cbase < cols) {
                            const int8_t *source=b+(size_t)(inner0+kbase+row)*n+col0+cbase;
                            for (col=0; col<4U && cbase+col<cols; ++col)
                                bp |= (uint32_t)(uint8_t)source[col] << (8U*col);
                        }
                        if (write_row(io, cache, &valid, core*8U+row, ap) ||
                            write_row(io, cache, &valid, core*8U+4U+row, bp)) return -1;
                    }
                }
                const int last_inner = inner0 + inner == k;
                if (io->write32(io->user, CTRL,
                                retain_accum && inner0 != 0U
                                    ? TINY3TPU_MMIO_CTRL_START_CONTINUE
                                    : TINY3TPU_MMIO_CTRL_START) || wait_done(io)) return -1;
                if (!retain_accum || last_inner) {
                    for (core = 0; core < 2U; ++core) {
                        const uint32_t rbase = row_parallel ? core*4U : 0U;
                        const uint32_t cbase = col_parallel ? core*4U : 0U;
                        /* Store column-parallel outputs in the second four
                         * rows of sums, keeping its existing 256-byte size. */
                        const uint32_t sbase = col_parallel ? core*4U : rbase;
                        /* With retained accumulators, a K-parallel core may
                         * have a nonzero partial even if this final K tail
                         * does not load operands for that core. */
                        if (k_parallel && !retain_accum && core*4U >= inner) continue;
                        if (rbase >= rows || cbase >= cols) continue;
                        const unsigned tile_rows=rows-rbase<4U ? rows-rbase : 4U;
                        const unsigned tile_cols=cols-cbase<4U ? cols-cbase : 4U;
                        if (read_tile(io,result_window,core,tile_rows,tile_cols,&sums[sbase])) return -1;
                    }
                }
                inner0 += inner;
            }
            for (row = 0; row < rows; ++row) {
                for (col = 0; col < cols; ++col) {
                    const int64_t sum = col_parallel ? sums[(col/4U)*4U+row][col%4U]
                                                     : sums[row][col];
                    if (sum < INT32_MIN || sum > INT32_MAX)
                        return -1;
                    output[(size_t)(row0+row)*n+col0+col] = (int32_t)sum;
                }
            }
            row0 += rows;
        }
        col0 += cols;
    }
    return 0;
}

/* Specialize the column mapping outside the hot loop. VexRiscv has a 2 KiB
 * instruction cache: carrying all three index mappings through every byte
 * pack evicts the mailbox code and can cost more than the saved launches. */
#define SCHEDULE_WRAPPER(name, columns) \
static int name(void *user, const int8_t *a, const int8_t *b, \
                const uint32_t *pa, const uint32_t *pb, int32_t *out, \
                uint32_t m, uint32_t k, uint32_t n) \
{ return qgemm_scheduled(user,a,b,pa,pb,out,m,k,n,columns); }
SCHEDULE_WRAPPER(qgemm_rows_k, 0)
SCHEDULE_WRAPPER(qgemm_columns, 1)
#undef SCHEDULE_WRAPPER

static int qgemm_impl(void *user, const int8_t *a, const int8_t *b,
                     const uint32_t *pa, const uint32_t *pb, int32_t *out,
                     uint32_t m, uint32_t k, uint32_t n)
{
    if (!m || !k || !n) return -1;
    /* Divide the common K tile factor before comparing axes, avoiding a
     * three-dimension integer product that could overflow for huge shapes. */
    const uint64_t mt4=1U+(m-1U)/4U, mt8=1U+(m-1U)/8U;
    const uint64_t kt4=1U+(k-1U)/4U, kt8=1U+(k-1U)/8U;
    const uint64_t nt4=1U+(n-1U)/4U, nt8=1U+(n-1U)/8U;
    const int beats_rows=mt4*nt8 < mt8*nt4;
    const int beats_k=kt4*nt8 < kt8*nt4;
    return beats_rows && beats_k ? qgemm_columns(user,a,b,pa,pb,out,m,k,n)
                                : qgemm_rows_k(user,a,b,pa,pb,out,m,k,n);
}

int tiny3tpu_mmio_qgemm(void *user, const int8_t *a, const int8_t *b,
                       int32_t *output, uint32_t m, uint32_t k, uint32_t n)
{
    return qgemm_impl(user, a, b, NULL, NULL, output, m, k, n);
}

int tiny3tpu_mmio_qgemm_packed(void *user, const int8_t *a, const int8_t *b,
                       const uint32_t *packed_a, const uint32_t *packed_b,
                       int32_t *output, uint32_t m, uint32_t k, uint32_t n)
{
    return qgemm_impl(user, a, b, packed_a, packed_b, output, m, k, n);
}
