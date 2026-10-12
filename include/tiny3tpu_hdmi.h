#ifndef TINY3TPU_HDMI_H
#define TINY3TPU_HDMI_H
#include <stdint.h>
#define TINY3TPU_HDMI_BASE UINT32_C(0x40000000)
#define TINY3TPU_HDMI_ID UINT32_C(0x48444d49)
static inline uint32_t tiny3tpu_hdmi_read(unsigned offset){
    __asm__ volatile("fence iorw, iorw":::"memory");
    return *(volatile uint32_t *)(uintptr_t)(TINY3TPU_HDMI_BASE+offset);
}
static inline void tiny3tpu_hdmi_write(unsigned offset,uint32_t value){
    *(volatile uint32_t *)(uintptr_t)(TINY3TPU_HDMI_BASE+offset)=value;
    __asm__ volatile("fence iorw, iorw":::"memory");
}
static inline int tiny3tpu_hdmi_submit(const int32_t *coordinates,unsigned vertex_count,unsigned phase){
    unsigned timeout=2000000;
    while(!(tiny3tpu_hdmi_read(4)&1U))if(!--timeout)return -1;
    for(unsigned i=0;i<vertex_count;i++){
        int32_t x=320+(coordinates[i*3]>>6),y=280-(coordinates[i*3+1]>>6);
        int32_t z=128+(coordinates[i*3+2]>>7);
        if(x<0||x>=640||y<0||y>=480||z<0||z>=255)return -2;
        tiny3tpu_hdmi_write(0x10000+i*4,(uint32_t)x|((uint32_t)y<<10)|((uint32_t)z<<20));
    }
    tiny3tpu_hdmi_write(8,UINT32_C(0x80000000)|(phase&255));
    return 0;
}
#endif
