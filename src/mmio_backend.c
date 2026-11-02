#include "tiny3tpu_mmio_backend.h"

#include <limits.h>
#include <stddef.h>

enum { CTRL = 0, CRD_CFG = 12,
       STATUS = 16, RESULT_LO = 20, RESULT_HI = 24 };

/* A retained int32 accumulator is safe for every legal K through this limit,
 * including the row-parallel schedule where one core sees the full K. */
enum { ACCUMULATOR_SAFE_MAX_K = 131071U };

enum {
    SCHED_ROWS = 0,
    SCHED_K = 1,
    SCHED_COLUMNS = 2,
    SCHED_GRID_2X4 = 3,
    SCHED_GRID_4X2 = 4
};

/* Cache only within this call: another caller or reset may change the device.
 * Full-word packed writes complete after all four byte stores are consumed.
 * Slots 0..119 cover the packed single-core and broadcast apertures 0x020..0x1fc. */
static int write_row(tiny3tpu_mmio *io, uint32_t cache[120], uint32_t valid[4],
                     uint32_t offset, uint32_t value)
{
    const unsigned slot = (unsigned)((offset - 0x20U) >> 2);
    const unsigned word = slot >> 5;
    const uint32_t bit = UINT32_C(1) << (slot & 31U);
    if ((valid[word] & bit) && cache[slot] == value) return 0;
    if (tiny3tpu_mmio_write(io, offset, value)) return -1;
    cache[slot] = value;
    valid[word] |= bit;
    return 0;
}

static int wait_done(tiny3tpu_mmio *io)
{
    uint32_t poll, status;
    int seen_busy = 0;
    for (poll = 0; poll < io->poll_limit; ++poll) {
        if (tiny3tpu_mmio_read(io, STATUS, &status)) return -1;
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
            if (tiny3tpu_mmio_read(io,0x200U+core*64U+row*16U+col*4U,&lo)) return -1;
        } else {
            uint32_t hi;
            const uint32_t cfg=(core<<8)|(row<<16)|(col<<24);
            if (tiny3tpu_mmio_write(io,CRD_CFG,cfg) || tiny3tpu_mmio_write(io,CTRL,4U) ||
                tiny3tpu_mmio_read(io,RESULT_LO,&lo) || tiny3tpu_mmio_read(io,RESULT_HI,&hi)) return -1;
            if (hi != ((lo&UINT32_C(0x80000000)) ? UINT32_MAX : 0U)) return -1;
        }
        sums[row][col] += lo <= INT32_MAX ? (int64_t)lo : (int64_t)lo-INT64_C(4294967296);
    }
    return 0;
}

static int select_schedule(uint32_t m, uint32_t k, uint32_t n)
{
    const uint64_t mt4 = 1U + (m - 1U) / 4U;
    const uint64_t mt8 = 1U + (m - 1U) / 8U;
    const uint64_t mt16 = 1U + (m - 1U) / 16U;
    const uint64_t mt32 = 1U + (m - 1U) / 32U;
    const uint64_t kt4 = 1U + (k - 1U) / 4U;
    const uint64_t kt32 = 1U + (k - 1U) / 32U;
    const uint64_t nt4 = 1U + (n - 1U) / 4U;
    const uint64_t nt8 = 1U + (n - 1U) / 8U;
    const uint64_t nt16 = 1U + (n - 1U) / 16U;
    const uint64_t nt32 = 1U + (n - 1U) / 32U;
    const uint64_t mn = (uint64_t)m * n;
    const uint64_t active_k_cores = kt4 < 8U ? kt4 : 8U;

    const uint64_t launches[5] = {
        mt32 * kt4 * nt4,
        mt4 * kt32 * nt4,
        mt4 * kt4 * nt32,
        mt8 * kt4 * nt16,
        mt16 * kt4 * nt8
    };
    const uint64_t a_words[5] = {
        (uint64_t)m * kt4 * nt4,
        (uint64_t)m * kt32 * nt4 * 8U,
        (uint64_t)m * kt4 * nt32,
        (uint64_t)m * kt4 * nt16,
        (uint64_t)m * kt4 * nt8
    };
    const uint64_t b_words[5] = {
        (uint64_t)k * nt4 * (k <= 4U ? 1U : mt32),
        (uint64_t)k * nt4 * (k <= 32U ? 1U : mt4),
        (uint64_t)k * nt4 * (k <= 4U ? 1U : mt4),
        (uint64_t)k * nt4 * (k <= 4U ? 1U : mt8),
        (uint64_t)k * nt4 * (k <= 4U ? 1U : mt16)
    };
    const uint64_t reads[5] = {
        mn,
        mn * active_k_cores,
        mn,
        mn,
        mn
    };

    int best = 0;
    uint64_t best_launches = launches[0];
    uint64_t best_tx = 1U + a_words[0] + b_words[0] + 2U * launches[0] + reads[0];
    for (int s = 1; s < 5; ++s) {
        const uint64_t tx = 1U + a_words[s] + b_words[s] + 2U * launches[s] + reads[s];
        if (launches[s] < best_launches ||
            (launches[s] == best_launches && tx < best_tx)) {
            best = s;
            best_launches = launches[s];
            best_tx = tx;
        }
    }
    return best;
}

static int qgemm_impl(void *user, const int8_t *a, const int8_t *b,
                      const uint32_t *packed_a, const uint32_t *packed_b,
                      int32_t *output, uint32_t m, uint32_t k, uint32_t n)
{
    tiny3tpu_mmio *io = user;
    uint32_t row0, col0, inner0, status, cache[120], valid[4] = {0};
    uint64_t ktile_count, a_words, b_words;
    if (io == NULL || io->read32 == NULL || io->write32 == NULL ||
        io->poll_limit == 0U || (a == NULL && packed_a == NULL) ||
        (b == NULL && packed_b == NULL) || output == NULL ||
        m == 0U || k == 0U || n == 0U ||
        (a != NULL && (uint64_t)m * k > SIZE_MAX) ||
        (b != NULL && (uint64_t)k * n > SIZE_MAX) ||
        (uint64_t)m * n > SIZE_MAX / sizeof(*output)) return -1;
    ktile_count = 1U + ((uint64_t)k - 1U) / 4U;
    a_words = (1U + ((uint64_t)m - 1U) / 4U) * ktile_count * 4U;
    b_words = (1U + ((uint64_t)n - 1U) / 4U) * ktile_count * 4U;
    if ((packed_a != NULL && a_words > SIZE_MAX / sizeof(*packed_a)) ||
        (packed_b != NULL && b_words > SIZE_MAX / sizeof(*packed_b))) return -1;
    if (tiny3tpu_mmio_read(io, STATUS, &status) || (status & 1U)) return -1;
    const int retain_accum =
        (status & TINY3TPU_MMIO_STATUS_ACCUM_CAP) != 0U &&
        k <= ACCUMULATOR_SAFE_MAX_K;
    const int result_window =
        (status & TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP) != 0U;
    const int sched = select_schedule(m, k, n);
    const uint32_t row_step = sched == SCHED_ROWS ? 32U :
                              sched == SCHED_GRID_4X2 ? 16U :
                              sched == SCHED_GRID_2X4 ? 8U : 4U;
    const uint32_t k_step = sched == SCHED_K ? 32U : 4U;
    const uint32_t col_step = sched == SCHED_COLUMNS ? 32U :
                              sched == SCHED_GRID_2X4 ? 16U :
                              sched == SCHED_GRID_4X2 ? 8U : 4U;
    const uint32_t a_group_count = sched == SCHED_COLUMNS ? 1U :
                                   sched == SCHED_GRID_2X4 ? 2U :
                                   sched == SCHED_GRID_4X2 ? 4U : 8U;
    const uint32_t b_group_count = sched == SCHED_ROWS ? 1U :
                                   sched == SCHED_GRID_4X2 ? 2U :
                                   sched == SCHED_GRID_2X4 ? 4U : 8U;

    for (col0 = 0; col0 < n;) {
        uint32_t cols = n - col0 < col_step ? n - col0 : col_step;
        for (row0 = 0; row0 < m;) {
            uint32_t rows = m - row0 < row_step ? m - row0 : row_step;
            int64_t sums[8][4][4] = {{{0}}};
            uint32_t row, col, core, g;
            for (inner0 = 0; inner0 < k;) {
                uint32_t inner = k - inner0 < k_step ? k - inner0 : k_step;
                for (g = 0; g < a_group_count; ++g) {
                    const uint32_t rbase = (sched == SCHED_ROWS ||
                                            sched == SCHED_GRID_2X4 ||
                                            sched == SCHED_GRID_4X2) ? g * 4U : 0U;
                    const uint32_t kbase = sched == SCHED_K ? g * 4U : 0U;
                    const uint32_t addr = sched == SCHED_COLUMNS ? 0x140U :
                                          sched == SCHED_GRID_2X4 ? 0x160U + g * 16U :
                                          sched == SCHED_GRID_4X2 ? 0x1c0U + g * 16U :
                                          0x040U + g * 32U;
                    for (row = 0; row < 4U; ++row) {
                        uint32_t ap = 0;
                        const uint32_t global_row = row0 + rbase + row;
                        const uint32_t global_inner_base = inner0 + kbase;
                        const int a_row_valid = rbase + row < rows;
                        if (packed_a != NULL && a_row_valid && kbase < inner) {
                            const size_t wi =
                                (((size_t)(global_row / 4U) * (size_t)ktile_count +
                                  global_inner_base / 4U) * 4U + global_row % 4U);
                            const uint32_t valid_lanes = inner - kbase < 4U ? inner - kbase : 4U;
                            ap = packed_a[wi];
                            if (valid_lanes < 4U)
                                ap &= (UINT32_C(1) << (8U * valid_lanes)) - 1U;
                        } else if (packed_a == NULL && a_row_valid && kbase < inner) {
                            const int8_t *source = a + (size_t)global_row * k + inner0 + kbase;
                            for (col = 0; col < 4U && kbase + col < inner; ++col)
                                ap |= (uint32_t)(uint8_t)source[col] << (8U * col);
                        }
                        if (write_row(io, cache, valid, addr + row * 4U, ap)) return -1;
                    }
                }
                for (g = 0; g < b_group_count; ++g) {
                    const uint32_t kbase = sched == SCHED_K ? g * 4U : 0U;
                    const uint32_t cbase = (sched == SCHED_COLUMNS ||
                                            sched == SCHED_GRID_2X4 ||
                                            sched == SCHED_GRID_4X2) ? g * 4U : 0U;
                    const uint32_t addr = sched == SCHED_ROWS ? 0x150U :
                                          sched == SCHED_GRID_2X4 ? 0x180U + g * 16U :
                                          sched == SCHED_GRID_4X2 ? 0x020U + g * 16U :
                                          0x050U + g * 32U;
                    for (row = 0; row < 4U; ++row) {
                        uint32_t bp = 0;
                        if (kbase + row < inner && cbase < cols) {
                            if (packed_b != NULL) {
                                const uint32_t global_inner = inner0 + kbase + row;
                                const size_t wi =
                                    (((size_t)((col0 + cbase) / 4U) * (size_t)ktile_count +
                                      global_inner / 4U) * 4U + global_inner % 4U);
                                const uint32_t valid_cols = cols - cbase < 4U ? cols - cbase : 4U;
                                bp = packed_b[wi];
                                if (valid_cols < 4U)
                                    bp &= (UINT32_C(1) << (8U * valid_cols)) - 1U;
                            } else {
                                const int8_t *source = b + (size_t)(inner0 + kbase + row) * n + col0 + cbase;
                                for (col = 0; col < 4U && cbase + col < cols; ++col)
                                    bp |= (uint32_t)(uint8_t)source[col] << (8U * col);
                            }
                        }
                        if (write_row(io, cache, valid, addr + row * 4U, bp)) return -1;
                    }
                }
                const int last_inner = inner0 + inner == k;
                if (tiny3tpu_mmio_write(io, CTRL,
                                        retain_accum && inner0 != 0U
                                            ? TINY3TPU_MMIO_CTRL_START_CONTINUE
                                            : TINY3TPU_MMIO_CTRL_START) || wait_done(io)) return -1;
                if (!retain_accum || last_inner) {
                    for (core = 0; core < 8U; ++core) {
                        const uint32_t rbase = sched == SCHED_ROWS ? core * 4U :
                                               sched == SCHED_GRID_2X4 ? (core / 4U) * 4U :
                                               sched == SCHED_GRID_4X2 ? (core / 2U) * 4U : 0U;
                        const uint32_t kbase = sched == SCHED_K ? core * 4U : 0U;
                        const uint32_t cbase = sched == SCHED_COLUMNS ? core * 4U :
                                               sched == SCHED_GRID_2X4 ? (core % 4U) * 4U :
                                               sched == SCHED_GRID_4X2 ? (core % 2U) * 4U : 0U;
                        const uint32_t s_idx = sched == SCHED_K ? 0U : core;
                        if (sched == SCHED_K && (retain_accum ? kbase >= k : kbase >= inner)) continue;
                        if (rbase >= rows || cbase >= cols) continue;
                        const unsigned tile_rows = rows - rbase < 4U ? rows - rbase : 4U;
                        const unsigned tile_cols = cols - cbase < 4U ? cols - cbase : 4U;
                        if (read_tile(io, result_window, core, tile_rows, tile_cols, sums[s_idx])) return -1;
                    }
                }
                inner0 += inner;
            }
            if (sched == SCHED_K) {
                for (row = 0; row < rows; ++row) {
                    for (col = 0; col < cols; ++col) {
                        const int64_t sum = sums[0][row][col];
                        if (sum < INT32_MIN || sum > INT32_MAX) return -1;
                        output[(size_t)(row0 + row) * n + col0 + col] = (int32_t)sum;
                    }
                }
            } else {
                for (core = 0; core < 8U; ++core) {
                    const uint32_t rbase = sched == SCHED_ROWS ? core * 4U :
                                           sched == SCHED_GRID_2X4 ? (core / 4U) * 4U :
                                           sched == SCHED_GRID_4X2 ? (core / 2U) * 4U : 0U;
                    const uint32_t cbase = sched == SCHED_COLUMNS ? core * 4U :
                                           sched == SCHED_GRID_2X4 ? (core % 4U) * 4U :
                                           sched == SCHED_GRID_4X2 ? (core % 2U) * 4U : 0U;
                    if (rbase >= rows || cbase >= cols) continue;
                    const uint32_t tile_rows = rows - rbase < 4U ? rows - rbase : 4U;
                    const uint32_t tile_cols = cols - cbase < 4U ? cols - cbase : 4U;
                    for (row = 0; row < tile_rows; ++row) {
                        for (col = 0; col < tile_cols; ++col) {
                            const int64_t sum = sums[core][row][col];
                            if (sum < INT32_MIN || sum > INT32_MAX) return -1;
                            output[(size_t)(row0 + rbase + row) * n + col0 + cbase + col] = (int32_t)sum;
                        }
                    }
                }
            }
            row0 += rows;
        }
        col0 += cols;
    }
    return 0;
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
