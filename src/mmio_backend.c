#include "tiny3tpu_mmio_backend.h"

#include <limits.h>
#include <stddef.h>

enum { CTRL = 0, CRD_CFG = 12,
       STATUS = 16, RESULT_LO = 20, RESULT_HI = 24 };

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

int tiny3tpu_mmio_qgemm(void *user, const int8_t *a, const int8_t *b,
                       int32_t *output, uint32_t m, uint32_t k, uint32_t n)
{
    tiny3tpu_mmio *io = user;
    uint32_t row0, col0, inner0, status, cache[16], valid = 0;
    if (io == NULL || io->read32 == NULL || io->write32 == NULL ||
        io->poll_limit == 0U || a == NULL || b == NULL || output == NULL ||
        m == 0U || k == 0U || n == 0U ||
        (uint64_t)m * k > SIZE_MAX || (uint64_t)k * n > SIZE_MAX ||
        (uint64_t)m * n > SIZE_MAX / sizeof(*output)) return -1;
    if (io->read32(io->user, STATUS, &status) || (status & 1U)) return -1;
    /* Choose the axis that needs fewer launches. In particular, short K uses
     * both cores for independent rows instead of launching a zero second core. */
    const uint64_t row_tiles = (uint64_t)(1U + (m-1U)/8U) * (1U + (k-1U)/4U);
    const uint64_t k_tiles = (uint64_t)(1U + (m-1U)/4U) * (1U + (k-1U)/8U);
    const int row_parallel = row_tiles <= k_tiles;
    const uint32_t row_step = row_parallel ? 8U : 4U;
    const uint32_t k_step = row_parallel ? 4U : 8U;
    for (col0 = 0; col0 < n;) {
        uint32_t cols = n-col0 < 4U ? n-col0 : 4U;
        for (row0 = 0; row0 < m;) {
            uint32_t rows = m-row0 < row_step ? m-row0 : row_step;
            int64_t sums[8][4] = {{0}};
            uint32_t row, col, core;
            for (inner0 = 0; inner0 < k;) {
                uint32_t inner = k-inner0 < k_step ? k-inner0 : k_step;
                for (core = 0; core < 2U; ++core) {
                    const uint32_t rbase = row_parallel ? core*4U : 0U;
                    const uint32_t kbase = row_parallel ? 0U : core*4U;
                    for (row = 0; row < 4U; ++row) {
                        uint32_t ap = 0, bp = 0;
                        for (col = 0; col < 4U; ++col) {
                            if (rbase+row < rows && kbase+col < inner)
                                ap |= (uint32_t)(uint8_t)a[(size_t)(row0+rbase+row)*k+inner0+kbase+col] << (8U*col);
                            if (kbase+row < inner && col < cols)
                                bp |= (uint32_t)(uint8_t)b[(size_t)(inner0+kbase+row)*n+col0+col] << (8U*col);
                        }
                        if (write_row(io, cache, &valid, core*8U+row, ap) ||
                            write_row(io, cache, &valid, core*8U+4U+row, bp)) return -1;
                    }
                }
                if (io->write32(io->user, CTRL, 1U) || wait_done(io)) return -1;
                for (core = 0; core < 2U; ++core) {
                    const uint32_t rbase = row_parallel ? core*4U : 0U;
                    if (!row_parallel && core*4U >= inner) continue;
                    for (row = 0; row < 4U && rbase+row < rows; ++row) {
                        for (col = 0; col < cols; ++col) {
                            uint32_t lo, hi;
                            const uint32_t cfg = (core << 8) | (row << 16) | (col << 24);
                            if (io->write32(io->user, CRD_CFG, cfg) ||
                                io->write32(io->user, CTRL, 4U) ||
                                io->read32(io->user, RESULT_LO, &lo) ||
                                io->read32(io->user, RESULT_HI, &hi)) return -1;
                            /* Fixed hardware produces a signed 32-bit tile;
                             * reject corrupt sign extension before summing. */
                            if (hi != ((lo & UINT32_C(0x80000000)) ? UINT32_MAX : 0U)) return -1;
                            sums[rbase+row][col] += lo <= INT32_MAX ? (int64_t)lo :
                                             (int64_t)lo - INT64_C(4294967296);
                        }
                    }
                }
                inner0 += inner;
            }
            for (row = 0; row < rows; ++row) {
                for (col = 0; col < cols; ++col) {
                    if (sums[row][col] < INT32_MIN || sums[row][col] > INT32_MAX)
                        return -1;
                    output[(size_t)(row0+row)*n+col0+col] = (int32_t)sums[row][col];
                }
            }
            row0 += rows;
        }
        col0 += cols;
    }
    return 0;
}
