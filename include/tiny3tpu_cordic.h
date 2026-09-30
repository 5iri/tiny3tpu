#ifndef TINY3TPU_CORDIC_H
#define TINY3TPU_CORDIC_H
#include <stdint.h>
#ifndef TINY3TPU_CORDIC_READ32
static inline uint32_t t3p_cordic_read(unsigned offset) {
 uint32_t value=*(volatile uint32_t *)(uintptr_t)(0x20003000U+offset);
 return value;
}
#define TINY3TPU_CORDIC_READ32 t3p_cordic_read
#endif
#ifndef TINY3TPU_CORDIC_WRITE32
static inline void t3p_cordic_write(unsigned offset,uint32_t value) {
 *(volatile uint32_t *)(uintptr_t)(0x20003000U+offset)=value;
}
#define TINY3TPU_CORDIC_WRITE32 t3p_cordic_write
#endif
static inline void t3p_cordic_fence(void) {
#ifdef __riscv
 __asm__ volatile("fence iorw, iorw" ::: "memory");
#endif
}
/* Explicit hardware target, no software fallback. Caller publishes outputs
 * only after success; missing identity, busy/rejected command and timeout fail. */
static inline int t3p_cordic_exp(float x,float *out) {
 union {float f;uint32_t u;} value={x};
 if(!out||TINY3TPU_CORDIC_READ32(12)!=0x45585031U)return -6;
 if(TINY3TPU_CORDIC_READ32(0)&1)return -6;
 TINY3TPU_CORDIC_WRITE32(0,2);
 TINY3TPU_CORDIC_WRITE32(4,value.u);t3p_cordic_fence();
 TINY3TPU_CORDIC_WRITE32(0,1);t3p_cordic_fence();
 for(unsigned poll=0;poll<1000;poll++) {
  uint32_t status=TINY3TPU_CORDIC_READ32(0);
  if(status&4)return -6;
  if(status&2){value.u=TINY3TPU_CORDIC_READ32(8);*out=value.f;return 0;}
 }
 return -6;
}
#endif
