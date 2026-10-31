#ifndef TINY3TPU_MMIO_BACKEND_H
#define TINY3TPU_MMIO_BACKEND_H

#include "tiny3tpu_runtime.h"

/* QGEMM control/status bits shared with the accelerator register block. */
#define TINY3TPU_MMIO_CTRL_START UINT32_C(1)
#define TINY3TPU_MMIO_CTRL_START_CONTINUE UINT32_C(9)
#define TINY3TPU_MMIO_STATUS_ACCUM_CAP UINT32_C(0x100)
#define TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP UINT32_C(0x200)

#ifdef __cplusplus
extern "C" {
#endif

/* Addresses are byte offsets from the accelerator base. Return zero on
 * success. Board callbacks must provide ordered device accesses. */
typedef struct tiny3tpu_mmio {
    void *user;
    int (*read32)(void *user, uint32_t offset, uint32_t *value);
    int (*write32)(void *user, uint32_t offset, uint32_t value);
    uint32_t poll_limit;
} tiny3tpu_mmio;

/* Helpers for compiler-generated kernels. Capability rejection happens before
 * any operand writes, so the caller can safely use the generic backend. */
#define TINY3TPU_MMIO_KERNEL_UNSUPPORTED 1

enum {
    TINY3TPU_SCHED_ROWS = 0,
    TINY3TPU_SCHED_K = 1,
    TINY3TPU_SCHED_COLUMNS = 2,
    TINY3TPU_SCHED_GRID_2X4 = 3,
    TINY3TPU_SCHED_GRID_4X2 = 4
};

static inline uint32_t tiny3tpu_mmio_min_u32(uint32_t a, uint32_t b)
{
    return a < b ? a : b;
}

/* Share protocol bookkeeping across shapes instead of duplicating it in every
 * kernel. This matters for the 64 KiB image and 2 KiB instruction cache. */
#if defined(__riscv) && defined(TINY3TPU_DIRECT_TPU) && (TINY3TPU_DIRECT_TPU != 0)
#define TINY3TPU_MMIO_FAST_DIRECT 1
#else
#define TINY3TPU_MMIO_FAST_DIRECT 0
#endif

static inline int tiny3tpu_mmio_write(tiny3tpu_mmio *io, uint32_t offset, uint32_t value)
{
#if TINY3TPU_MMIO_FAST_DIRECT
    if (!io->user) {
        *(volatile uint32_t *)(uintptr_t)(0x20001000U + offset) = value;
        return 0;
    }
#endif
    return io->write32(io->user, offset, value);
}

static inline int tiny3tpu_mmio_read(tiny3tpu_mmio *io, uint32_t offset, uint32_t *value)
{
#if TINY3TPU_MMIO_FAST_DIRECT
    if (!io->user) {
        *value = *(volatile uint32_t *)(uintptr_t)(0x20001000U + offset);
        return 0;
    }
#endif
    return io->read32(io->user, offset, value);
}

#if defined(__GNUC__)
#define TINY3TPU_MMIO_KERNEL_HELPER static __attribute__((noinline, unused))
#else
#define TINY3TPU_MMIO_KERNEL_HELPER static inline
#endif
TINY3TPU_MMIO_KERNEL_HELPER int tiny3tpu_mmio_kernel_begin(tiny3tpu_mmio *io)
{
    uint32_t status;
    const uint32_t caps = TINY3TPU_MMIO_STATUS_ACCUM_CAP |
                          TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP;
    if (!io || !io->read32 || !io->write32 || !io->poll_limit) return -1;
    if (tiny3tpu_mmio_read(io, 16U, &status) || (status & 1U)) return -1;
    return (status & caps) == caps ? 0 : TINY3TPU_MMIO_KERNEL_UNSUPPORTED;
}

TINY3TPU_MMIO_KERNEL_HELPER int tiny3tpu_mmio_kernel_start(tiny3tpu_mmio *io, uint32_t control)
{
    int seen_busy = 0;
    if (tiny3tpu_mmio_write(io, 0U, control)) return -1;
    for (uint32_t poll = 0; poll < io->poll_limit; ++poll) {
        uint32_t status;
        if (tiny3tpu_mmio_read(io, 16U, &status)) return -1;
        if (status & 2U) return 0;
        if (status & 1U) seen_busy = 1;
        else if (seen_busy) return 0;
    }
    return -1;
}
#undef TINY3TPU_MMIO_KERNEL_HELPER

#define TINY3TPU_PACK_ROW_A(r_idx, k_idx, lanes)                               \
    (((lanes) > 0U ? (uint32_t)(uint8_t)T3P_MMIO_A((r_idx), (k_idx)) : 0U) |   \
     ((lanes) > 1U ? ((uint32_t)(uint8_t)T3P_MMIO_A((r_idx), (k_idx) + 1U) << 8U) : 0U) | \
     ((lanes) > 2U ? ((uint32_t)(uint8_t)T3P_MMIO_A((r_idx), (k_idx) + 2U) << 16U) : 0U) | \
     ((lanes) > 3U ? ((uint32_t)(uint8_t)T3P_MMIO_A((r_idx), (k_idx) + 3U) << 24U) : 0U))

#define TINY3TPU_PACK_ROW_B(k_idx, c_idx, lanes)                               \
    (((lanes) > 0U ? (uint32_t)(uint8_t)T3P_MMIO_B((k_idx), (c_idx)) : 0U) |   \
     ((lanes) > 1U ? ((uint32_t)(uint8_t)T3P_MMIO_B((k_idx), (c_idx) + 1U) << 8U) : 0U) | \
     ((lanes) > 2U ? ((uint32_t)(uint8_t)T3P_MMIO_B((k_idx), (c_idx) + 2U) << 16U) : 0U) | \
     ((lanes) > 3U ? ((uint32_t)(uint8_t)T3P_MMIO_B((k_idx), (c_idx) + 3U) << 24U) : 0U))

#define TINY3TPU_MMIO_LOAD_B(io, c, cols, t, inner, KT, SCHED, HAS_PB)         \
    do {                                                                       \
        if ((SCHED) == TINY3TPU_SCHED_K) {                                     \
            for (uint32_t kb = 0U, kg = 0U; kb < (inner); kb += 4U, ++kg) {    \
                const uint32_t r_lim = tiny3tpu_mmio_min_u32(4U, (inner) - kb);\
                const uint32_t c_lanes = tiny3tpu_mmio_min_u32(4U, (cols));    \
                for (uint32_t row = 0U; row < r_lim; ++row) {                  \
                    const uint32_t word = (HAS_PB)                             \
                        ? T3P_MMIO_PB((((c) / 4U) * (KT) + ((t) + kb) / 4U) * 4U + row) \
                        : TINY3TPU_PACK_ROW_B((t) + kb + row, (c), c_lanes);   \
                    if (tiny3tpu_mmio_write((io), 0x050U + kg * 32U + row * 4U, word)) return -1; \
                }                                                              \
            }                                                                  \
        } else {                                                               \
            const uint32_t b_base = (SCHED) == TINY3TPU_SCHED_ROWS ? 0x150U :  \
                                    (SCHED) == TINY3TPU_SCHED_GRID_2X4 ? 0x180U : \
                                    (SCHED) == TINY3TPU_SCHED_GRID_4X2 ? 0x020U : 0x050U; \
            const uint32_t b_stride = (SCHED) == TINY3TPU_SCHED_ROWS ? 0U :    \
                                      (SCHED) == TINY3TPU_SCHED_COLUMNS ? 32U : 16U; \
            const uint32_t r_lim = tiny3tpu_mmio_min_u32(4U, (inner));         \
            for (uint32_t cb = 0U, cg = 0U; cb < (cols); cb += 4U, ++cg) {     \
                const uint32_t c_lanes = tiny3tpu_mmio_min_u32(4U, (cols) - cb);\
                for (uint32_t row = 0U; row < r_lim; ++row) {                  \
                    const uint32_t word = (HAS_PB)                             \
                        ? T3P_MMIO_PB(((((c) + cb) / 4U) * (KT) + ((t) / 4U)) * 4U + row) \
                        : TINY3TPU_PACK_ROW_B((t) + row, (c) + cb, c_lanes);   \
                    if (tiny3tpu_mmio_write((io), b_base + cg * b_stride + row * 4U, word)) return -1; \
                }                                                              \
            }                                                                  \
        }                                                                      \
    } while (0)

#define TINY3TPU_MMIO_KERNEL_BODY(M, K, N, KT, SCHED, HAS_PA, HAS_PB)          \
    const uint32_t rs = (SCHED) == TINY3TPU_SCHED_ROWS ? 32U :                 \
                        (SCHED) == TINY3TPU_SCHED_GRID_4X2 ? 16U :             \
                        (SCHED) == TINY3TPU_SCHED_GRID_2X4 ? 8U : 4U;          \
    const uint32_t ks = (SCHED) == TINY3TPU_SCHED_K ? 32U : 4U;                \
    const uint32_t cs = (SCHED) == TINY3TPU_SCHED_COLUMNS ? 32U :              \
                        (SCHED) == TINY3TPU_SCHED_GRID_2X4 ? 16U :             \
                        (SCHED) == TINY3TPU_SCHED_GRID_4X2 ? 8U : 4U;          \
    uint32_t value = 0U;                                                       \
    for (uint32_t c = 0U; c < (N); c += cs) {                                  \
        const uint32_t cols = tiny3tpu_mmio_min_u32(cs, (N) - c);              \
        if ((K) <= ks) {                                                       \
            TINY3TPU_MMIO_LOAD_B(io, c, cols, 0U, (K), (KT), (SCHED), (HAS_PB)); \
        }                                                                      \
        for (uint32_t r = 0U; r < (M); r += rs) {                              \
            const uint32_t row_count = tiny3tpu_mmio_min_u32(rs, (M) - r);     \
            for (uint32_t t = 0U; t < (K); t += ks) {                          \
                const uint32_t inner = tiny3tpu_mmio_min_u32(ks, (K) - t);     \
                if ((SCHED) == TINY3TPU_SCHED_K) {                             \
                    const uint32_t r_lim = tiny3tpu_mmio_min_u32(4U, row_count); \
                    for (uint32_t kg = 0U; kg < 8U; ++kg) {                    \
                        const uint32_t kb = kg * 4U;                           \
                        const uint32_t lanes = kb < inner ? tiny3tpu_mmio_min_u32(4U, inner - kb) : 0U; \
                        for (uint32_t row = 0U; row < r_lim; ++row) {          \
                            const uint32_t word = ((HAS_PA) && lanes != 0U)    \
                                ? T3P_MMIO_PA(((r / 4U) * (KT) + (t + kb) / 4U) * 4U + row) \
                                : TINY3TPU_PACK_ROW_A(r + row, t + kb, lanes); \
                            if (tiny3tpu_mmio_write(io, 0x040U + kg * 32U + row * 4U, word)) return -1; \
                        }                                                      \
                    }                                                          \
                } else {                                                       \
                    const uint32_t a_base = (SCHED) == TINY3TPU_SCHED_COLUMNS ? 0x140U : \
                                            (SCHED) == TINY3TPU_SCHED_GRID_2X4 ? 0x160U : \
                                            (SCHED) == TINY3TPU_SCHED_GRID_4X2 ? 0x1c0U : 0x040U; \
                    const uint32_t a_stride = (SCHED) == TINY3TPU_SCHED_COLUMNS ? 0U : \
                                              (SCHED) == TINY3TPU_SCHED_ROWS ? 32U : 16U; \
                    const uint32_t lanes = tiny3tpu_mmio_min_u32(4U, inner);   \
                    for (uint32_t rb = 0U, rg = 0U; rb < row_count; rb += 4U, ++rg) { \
                        const uint32_t r_lim = tiny3tpu_mmio_min_u32(4U, row_count - rb); \
                        for (uint32_t row = 0U; row < r_lim; ++row) {          \
                            const uint32_t word = (HAS_PA)                     \
                                ? T3P_MMIO_PA((((r + rb) / 4U) * (KT) + (t / 4U)) * 4U + row) \
                                : TINY3TPU_PACK_ROW_A(r + rb + row, t, lanes); \
                            if (tiny3tpu_mmio_write(io, a_base + rg * a_stride + row * 4U, word)) return -1; \
                        }                                                      \
                    }                                                          \
                }                                                              \
                if ((K) > ks) {                                                \
                    TINY3TPU_MMIO_LOAD_B(io, c, cols, t, inner, (KT), (SCHED), (HAS_PB)); \
                }                                                              \
                if (tiny3tpu_mmio_kernel_start(io, t == 0U ? 1U : 9U)) return -1; \
            }                                                                  \
            if ((SCHED) == TINY3TPU_SCHED_ROWS) {                              \
                for (uint32_t row = 0U; row < row_count; ++row)                \
                    for (uint32_t col = 0U; col < cols; ++col) {               \
                        if (tiny3tpu_mmio_read(io, 0x200U + row * 16U + col * 4U, &value)) return -1; \
                        T3P_MMIO_OUT(r + row, c + col) = t3p_i32(value);       \
                    }                                                          \
            } else if ((SCHED) == TINY3TPU_SCHED_K) {                          \
                const uint32_t active_k = tiny3tpu_mmio_min_u32(8U, (KT));     \
                for (uint32_t core = 0U; core < active_k; ++core)              \
                    for (uint32_t row = 0U; row < row_count; ++row)            \
                        for (uint32_t col = 0U; col < cols; ++col) {           \
                            if (tiny3tpu_mmio_read(io, 0x200U + core * 64U + row * 16U + col * 4U, &value)) return -1; \
                            T3P_MMIO_OUT(r + row, c + col) = t3p_i32(core ? (uint32_t)T3P_MMIO_OUT(r + row, c + col) + value : value); \
                        }                                                      \
            } else {                                                           \
                for (uint32_t core = 0U; core < 8U; ++core) {                  \
                    const uint32_t rb = (SCHED) == TINY3TPU_SCHED_GRID_2X4 ? (core / 4U) * 4U : \
                                        (SCHED) == TINY3TPU_SCHED_GRID_4X2 ? (core / 2U) * 4U : 0U; \
                    const uint32_t cb = (SCHED) == TINY3TPU_SCHED_COLUMNS ? core * 4U : \
                                        (SCHED) == TINY3TPU_SCHED_GRID_2X4 ? (core % 4U) * 4U : \
                                        (core % 2U) * 4U;                      \
                    if (rb >= row_count || cb >= cols) continue;               \
                    const uint32_t r_lim = tiny3tpu_mmio_min_u32(4U, row_count - rb); \
                    const uint32_t c_lim = tiny3tpu_mmio_min_u32(4U, cols - cb); \
                    for (uint32_t row = 0U; row < r_lim; ++row)                \
                        for (uint32_t col = 0U; col < c_lim; ++col) {           \
                            if (tiny3tpu_mmio_read(io, 0x200U + core * 64U + row * 16U + col * 4U, &value)) return -1; \
                            T3P_MMIO_OUT(r + rb + row, c + cb + col) = t3p_i32(value); \
                        }                                                      \
                }                                                              \
            }                                                                  \
        }                                                                      \
    }                                                                          \
    return 0;

#define TINY3TPU_DEFINE_MMIO_KERNEL_CTX(NAME, CTX_T, WORD_T, M, K, N, KT, SCHED, HAS_PA, HAS_PB) \
    static int NAME(tiny3tpu_mmio *io, void *opaque) {                         \
        int status = tiny3tpu_mmio_kernel_begin(io);                           \
        if (status) return status;                                             \
        CTX_T *context = (CTX_T *)opaque;                                      \
        WORD_T *w = context->w;                                                \
        uint32_t batch = context->batch;                                       \
        (void)w; (void)batch;                                                  \
        TINY3TPU_MMIO_KERNEL_BODY(M, K, N, KT, SCHED, HAS_PA, HAS_PB)          \
    }

#define TINY3TPU_DEFINE_MMIO_KERNEL_PTRS(NAME, CTX_T, WORD_T, M, K, N, KT, SCHED, HAS_PA, HAS_PB) \
    static int NAME(tiny3tpu_mmio *io, void *opaque) {                         \
        int status = tiny3tpu_mmio_kernel_begin(io);                           \
        if (status) return status;                                             \
        CTX_T *context = (CTX_T *)opaque;                                      \
        WORD_T *w = 0;                                                         \
        uint32_t batch = 0U;                                                   \
        WORD_T *lhs_data = context->lhs, *rhs_data = context->rhs, *output_data = context->output; \
        const uint32_t *packed_lhs = context->packed_a, *packed_rhs = context->packed_b; \
        (void)w; (void)batch; (void)lhs_data; (void)rhs_data; (void)output_data; \
        (void)packed_lhs; (void)packed_rhs;                                    \
        TINY3TPU_MMIO_KERNEL_BODY(M, K, N, KT, SCHED, HAS_PA, HAS_PB)          \
    }

static inline int tiny3tpu_mmio_run_kernel(void *user,
                                         tiny3tpu_mmio_kernel kernel,
                                         void *context)
{
    return kernel ? kernel((tiny3tpu_mmio *)user, context) : -1;
}

/* QGEMM callback for eight signed-int8 4x4 cores with the PACKED_ROW
 * (0x040..0x13c), PACKED_BCAST (0x020..0x03c, 0x140..0x1fc) and RESULT_WINDOW
 * (0x200..0x3fc) apertures. user points to tiny3tpu_mmio. Requires exclusive
 * device ownership for the duration of the call; no cached operand state
 * survives the call.
 * A[M,K], B[K,N], native int32 output[M,N]. No bias or requantization here.
 * Returns nonzero on bus errors, timeout, or int32 result overflow. */
int tiny3tpu_mmio_qgemm(void *user, const int8_t *a, const int8_t *b,
                       int32_t *output, uint32_t m, uint32_t k, uint32_t n);

/* As above, with optional operands supplied in numeric little-byte-order
 * 4x4 row words. Packed A needs ceil(M/4)*ceil(K/4)*4 words. Its word index is
 * ((row/4)*ceil(K/4)+k/4)*4+row%4; byte lane k%4 contains A[row,k]. Packed B
 * needs ceil(N/4)*ceil(K/4)*4 words. Its word index is
 * ((col/4)*ceil(K/4)+k/4)*4+k%4; byte lane col%4 contains B[k,col]. Padded
 * rows, columns and K lanes are zero. Raw operands may be NULL only when the
 * matching packed operand is present. This layout is independent of core schedule. */
int tiny3tpu_mmio_qgemm_packed(void *user, const int8_t *a, const int8_t *b,
                       const uint32_t *packed_a, const uint32_t *packed_b,
                       int32_t *output, uint32_t m, uint32_t k, uint32_t n);

#ifdef __cplusplus
}
#endif
#endif
