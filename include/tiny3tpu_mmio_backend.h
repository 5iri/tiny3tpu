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
