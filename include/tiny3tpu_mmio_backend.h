#ifndef TINY3TPU_MMIO_BACKEND_H
#define TINY3TPU_MMIO_BACKEND_H

#include "tiny3tpu_runtime.h"

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

#ifdef __cplusplus
}
#endif
#endif
