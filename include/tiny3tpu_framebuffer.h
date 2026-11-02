#ifndef TINY3TPU_FRAMEBUFFER_H
#define TINY3TPU_FRAMEBUFFER_H
#include <stdint.h>
#include <stddef.h>
#define TINY3TPU_FB_CONTROL UINT32_C(0x40000000)
#define TINY3TPU_FB_PIXELS UINT32_C(0x40100000)
#define TINY3TPU_FB_ID UINT32_C(0x50464231)
#ifndef TINY3TPU_FB_WIDTH
#define TINY3TPU_FB_WIDTH 160U
#endif
#ifndef TINY3TPU_FB_HEIGHT
#define TINY3TPU_FB_HEIGHT 120U
#endif
#define TINY3TPU_FB_WORDS (TINY3TPU_FB_WIDTH*TINY3TPU_FB_HEIGHT/2U)
static inline uint32_t tiny3tpu_fb_read(unsigned offset){
    __asm__ volatile("fence iorw, iorw":::"memory");
    return *(volatile uint32_t *)(uintptr_t)(TINY3TPU_FB_CONTROL+offset);
}
static inline int tiny3tpu_fb_check(void){
    return tiny3tpu_fb_read(0)==TINY3TPU_FB_ID &&
        tiny3tpu_fb_read(0x10)==TINY3TPU_FB_WIDTH &&
        tiny3tpu_fb_read(0x14)==TINY3TPU_FB_HEIGHT &&
        tiny3tpu_fb_read(0x24)==565U ? 0 : -1;
}
/* Returns 1 when a prior frame is pending, allowing training to continue.
 * Pixels are two little-endian RGB565 values per word. The caller retains
 * ownership; after this synchronous upload it may immediately reuse its buffer.
 */
static inline int tiny3tpu_fb_present(const uint32_t *pixels,size_t words,uint32_t tag){
    if(!pixels || words!=TINY3TPU_FB_WORDS)return -1;
    if(!(tiny3tpu_fb_read(4)&1U))return 1;
    volatile uint32_t *dest=(volatile uint32_t *)(uintptr_t)TINY3TPU_FB_PIXELS;
    for(size_t i=0;i<words;i++)dest[i]=pixels[i];
    __asm__ volatile("fence iorw, iorw":::"memory");
    *(volatile uint32_t *)(uintptr_t)(TINY3TPU_FB_CONTROL+8)=tag;
    __asm__ volatile("fence iorw, iorw":::"memory");
    return 0;
}
#endif
