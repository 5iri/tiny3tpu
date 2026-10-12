#ifndef TINY3TPU_UART_COORDS_H
#define TINY3TPU_UART_COORDS_H
#include <stdint.h>

/* Lossless wire encoding for an angle followed by XYZ float32 coordinates.
 * Integral coordinates use one signed base per axis and unsigned 16-bit
 * offsets. Arbitrary floats, negative zero and larger spans use the original
 * float32 payload. Each response is independently decodable (no frame state).
 * Inspect bits to avoid software float conversion/division on RV32IM. */
static inline int tiny3tpu_uart_exact_i32(float value, int32_t *result)
{
    union { float f; uint32_t u; } bits = {value};
    uint32_t magnitude = bits.u & UINT32_C(0x7fffffff);
    if (!magnitude) {
        if (bits.u) return 0; /* Preserve the sign bit of -0 through fallback. */
        *result = 0;
        return 1;
    }
    if (bits.u == UINT32_C(0xcf000000)) {
        *result = INT32_MIN;
        return 1;
    }
    int exponent = (int)(magnitude >> 23) - 127;
    if (exponent < 0 || exponent > 30) return 0;
    uint32_t significand = (magnitude & UINT32_C(0x7fffff)) | UINT32_C(0x800000);
    if (exponent < 23) {
        unsigned shift = (unsigned)(23-exponent);
        if (significand & ((UINT32_C(1) << shift)-1U)) return 0;
        magnitude = significand >> shift;
    } else magnitude = significand << (unsigned)(exponent-23);
    *result = bits.u >> 31 ? -(int32_t)magnitude : (int32_t)magnitude;
    return 1;
}

static inline int tiny3tpu_uart_coords_prepare(const float *values, uint32_t words,
                                              int32_t base[3])
{
    int32_t high[3];
    if (words < 4 || (words-1U)%3U) return 0;
    for (unsigned axis=0; axis<3; ++axis) {
        if (!tiny3tpu_uart_exact_i32(values[1+axis], &base[axis])) return 0;
        high[axis] = base[axis];
    }
    unsigned axis=0;
    for (uint32_t i=1; i<words; ++i) {
        int32_t value;
        if (!tiny3tpu_uart_exact_i32(values[i], &value)) return 0;
        if (value < base[axis]) base[axis] = value;
        if (value > high[axis]) high[axis] = value;
        if (++axis == 3) axis=0;
    }
    for (axis=0; axis<3; ++axis)
        if ((uint32_t)high[axis] - (uint32_t)base[axis] > UINT16_MAX) return 0;
    return 1;
}

/* Call only after prepare succeeds for these same values and bases. */
static inline uint16_t tiny3tpu_uart_coord_offset(float value, int32_t base)
{
    int32_t integer=0;
    (void)tiny3tpu_uart_exact_i32(value, &integer);
    return (uint16_t)((uint32_t)integer-(uint32_t)base);
}
#endif
