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
/* Share protocol bookkeeping across shapes instead of duplicating it in every
 * kernel. This matters for the 64 KiB image and 2 KiB instruction cache. */
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
    if (io->read32(io->user, 16U, &status) || (status & 1U)) return -1;
    return (status & caps) == caps ? 0 : TINY3TPU_MMIO_KERNEL_UNSUPPORTED;
}

TINY3TPU_MMIO_KERNEL_HELPER int tiny3tpu_mmio_kernel_start(tiny3tpu_mmio *io, uint32_t control)
{
    int seen_busy = 0;
    if (io->write32(io->user, 0U, control)) return -1;
    for (uint32_t poll = 0; poll < io->poll_limit; ++poll) {
        uint32_t status;
        if (io->read32(io->user, 16U, &status)) return -1;
        if (status & 2U) return 0;
        if (status & 1U) seen_busy = 1;
        else if (seen_busy) return 0;
    }
    return -1;
}
#undef TINY3TPU_MMIO_KERNEL_HELPER

static inline int tiny3tpu_mmio_run_kernel(void *user,
                                         tiny3tpu_mmio_kernel kernel,
                                         void *context)
{
    return kernel ? kernel((tiny3tpu_mmio *)user, context) : -1;
}

/* QGEMM callback for two signed-int8 4x4 cores with the PACKED_ROW aperture
 * (0x40..0x7c). user points to tiny3tpu_mmio. Requires exclusive device ownership
 * for the duration of the call; no cached operand state survives the call.
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
