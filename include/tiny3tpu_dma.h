#ifndef TINY3TPU_DMA_H
#define TINY3TPU_DMA_H
#include <stdint.h>

/* TDM1 native register ABI for the open AXI DMA wrapper. Buffers must be
 * disjoint, contiguous, uncached physical DDR memory. After a timeout they
 * remain owned by DMA until a coordinated system reset; do not reuse them. */
typedef struct tiny3tpu_dma {
    volatile uint32_t *registers;
    volatile uint32_t *commands;
    volatile uint32_t *responses;
    uint32_t capacity; /* Two-word commands, with equally sized responses. */
    uint32_t poll_limit;
    int poisoned;
} tiny3tpu_dma;

int tiny3tpu_dma_init(tiny3tpu_dma *dma);
int tiny3tpu_dma_submit(tiny3tpu_dma *dma, uint32_t commands);
int tiny3tpu_dma_qgemm(void *user, const int8_t *a, const int8_t *b,
                      int32_t *output, uint32_t m, uint32_t k, uint32_t n);
#endif
