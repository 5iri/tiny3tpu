#include "tiny3tpu_uart_coords.h"
#include <stdio.h>
#include <string.h>

static int roundtrip(const float *values, unsigned words)
{
    int32_t base[3];
    if (!tiny3tpu_uart_coords_prepare(values, words, base)) return 0;
    for (unsigned i=1; i<words; ++i) {
        unsigned axis=(i-1)%3;
        uint16_t offset=tiny3tpu_uart_coord_offset(values[i],base[axis]);
        float decoded=(float)((int64_t)base[axis]+offset);
        if (memcmp(&decoded,&values[i],sizeof(decoded))) return 0;
    }
    return 1;
}

int main(void)
{
    int32_t value,base[3];
    const uint32_t edge_bits[]={0,0x80000000,1,0x007fffff,0x3f000000,0x3f800000,
        0xbf800000,0x7f800000,0xff800000,0x7fc12345,0xcf000000,0x4effffff,
        0x4f000000,0xcf000001,0x4b800001};
    uint32_t random=705;
    for (unsigned i=0;i<200000+sizeof(edge_bits)/sizeof(*edge_bits);++i) {
        random=random*1664525U+1013904223U;
        union {uint32_t u;float f;} sample={i<sizeof(edge_bits)/sizeof(*edge_bits)?edge_bits[i]:random};
        const double wide=sample.f;
        int valid=wide>=INT32_MIN && wide<=INT32_MAX && sample.u!=0x80000000U;
        if (valid) valid=sample.f==(float)(int32_t)sample.f;
        int got=tiny3tpu_uart_exact_i32(sample.f,&value);
        if (got!=valid || (got && (float)value!=sample.f)) return 1;
    }
    float coordinates[]={.25f,-32768.f,-100.f,10000.f,32767.f,100.f,20000.f};
    if (!roundtrip(coordinates,7)) return 2;
    coordinates[4]=32768.f; /* Span 65536 cannot be represented. */
    if (tiny3tpu_uart_coords_prepare(coordinates,7,base)) return 3;
    coordinates[4]=-0.f;
    if (tiny3tpu_uart_coords_prepare(coordinates,7,base)) return 4;
    coordinates[4]=.5f;
    if (tiny3tpu_uart_coords_prepare(coordinates,7,base)) return 5;
    if (tiny3tpu_uart_coords_prepare(coordinates,6,base) ||
        tiny3tpu_uart_coords_prepare(coordinates,1,base)) return 6;
    float extremes[]={0.f,-0x1p31f,0x1p30f,0.f,-0x1p31f+32768.f,0x1p30f+32768.f,65535.f};
    if (!roundtrip(extremes,7)) return 7;
    extremes[4]=0x1p30f;
    if (tiny3tpu_uart_coords_prepare(extremes,7,base)) return 8;
    float frame[613]={0};
    for (unsigned iteration=0;iteration<100;++iteration) {
        for (unsigned i=1;i<613;++i) {
            random=random*1664525U+1013904223U;
            frame[i]=(float)((int32_t)(random&65535U)-32768+(int32_t)((i-1)%3)*100000);
        }
        if (!roundtrip(frame,613)) return 9;
    }
    puts("PASS: lossless UART coordinates, 200k float patterns, spans and fallback");
    return 0;
}
