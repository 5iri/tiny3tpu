/* JAX-generated transforms on VexRiscv and both 4x4 TPUs, then HDMI MMIO. */
#include <stddef.h>
#include <stdint.h>
#include "banana_spinner369.h"
#include "jax_expected.h"
#include "tiny3tpu_mmio_backend.h"
#include "tiny3tpu_hdmi.h"
static banana_spinner369_workspace workspace;
static int32_t coordinates[JAX_VERTEX_COUNT*3],phase_input[1];
static unsigned backend_calls;
void *memcpy(void *d,const void *s,size_t n){unsigned char *a=d;const unsigned char *b=s;for(size_t i=0;i<n;i++)a[i]=b[i];return d;}
void *memset(void *d,int x,size_t n){unsigned char *a=d;for(size_t i=0;i<n;i++)a[i]=(unsigned char)x;return d;}
static int rd(void *u,uint32_t a,uint32_t *v){(void)u;*v=*(volatile uint32_t *)(uintptr_t)(0x20001000U+a);return 0;}
static int wr(void *u,uint32_t a,uint32_t v){(void)u;*(volatile uint32_t *)(uintptr_t)(0x20001000U+a)=v;return 0;}
static int gemm(void *u,const int8_t *a,const int8_t *b,int32_t *c,uint32_t m,uint32_t k,uint32_t n){backend_calls++;return tiny3tpu_mmio_qgemm(u,a,b,c,m,k,n);}
static int packed(void *u,const int8_t *a,const int8_t *b,const uint32_t *pa,const uint32_t *pb,int32_t *c,uint32_t m,uint32_t k,uint32_t n){
    backend_calls++;
    /* Specialize this workload's Mx3 * 3x3 GEMM. Both real cores process four
     * rows per launch. Three INT8 products always fit INT32, so no software
     * INT64 reduction or general K/column scheduling is needed here. */
    if(m!=JAX_VERTEX_COUNT || k!=3 || n!=3 || !pa || !b || pb)
        return tiny3tpu_mmio_qgemm_packed(u,a,b,pa,pb,c,m,k,n);
    volatile uint32_t *tpu=(volatile uint32_t *)(uintptr_t)0x20001000U;
    uint32_t status=tpu[4];
    if((status&1U) || !(status&TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP))return -1;
    for(unsigned row=0;row<4;row++){
        uint32_t v=row<3 ? (uint32_t)(uint8_t)b[row*3] |
            ((uint32_t)(uint8_t)b[row*3+1]<<8) | ((uint32_t)(uint8_t)b[row*3+2]<<16) : 0;
        tpu[0x50/4+row]=v;tpu[0x70/4+row]=v;
    }
    for(unsigned base=0;base<m;base+=8){
        for(unsigned row=0;row<4;row++){
            tpu[0x40/4+row]=base+row<m ? pa[base+row]&0xffffffU : 0;
            tpu[0x60/4+row]=base+4+row<m ? pa[base+4+row]&0xffffffU : 0;
        }
        __asm__ volatile("fence iorw, iorw":::"memory");
        tpu[0]=TINY3TPU_MMIO_CTRL_START;
        unsigned polls=1000;
        while(!(tpu[4]&2U))if(!--polls)return -1;
        __asm__ volatile("fence iorw, iorw":::"memory");
        for(unsigned row=0;row<8 && base+row<m;row++){
            volatile uint32_t *result=tpu+0x80/4+(row/4)*16+(row%4)*4;
            c[(base+row)*3]=(int32_t)result[0];
            c[(base+row)*3+1]=(int32_t)result[1];
            c[(base+row)*3+2]=(int32_t)result[2];
        }
    }
    return 0;
}
int main(void){
    tiny3tpu_mmio io={0,rd,wr,1000};
    tiny3tpu_qgemm_backend backend={&io,gemm,packed,0};
    if(tiny3tpu_hdmi_read(0)!=TINY3TPU_HDMI_ID)return 1;
    if(tiny3tpu_hdmi_read(0x24)!=JAX_VERTEX_COUNT)return 1;
    const void *inputs[]={phase_input};void *outputs[]={coordinates};
    unsigned phase=0,speed=1,paused=0;
    for(;;){
        unsigned pressed=tiny3tpu_hdmi_read(0x14),held=tiny3tpu_hdmi_read(0x10);
        tiny3tpu_hdmi_write(0x14,pressed);
        if(pressed&1U)paused^=1;
        if((pressed&4U)&&speed<4)speed++;
        if((pressed&8U)&&speed>1)speed--;
        phase_input[0]=(int32_t)phase;backend_calls=0;
        int status=banana_spinner369_run(inputs,outputs,&workspace,&backend);
        if(status||backend_calls!=1)return 2;
        /* Verify the first phase exactly against JAX, including on the board. */
        if(phase<JAX_VERIFY_PHASES)for(unsigned i=0;i<JAX_VERTEX_COUNT*3;i++)
            if(coordinates[i]!=jax_expected[phase][i])return 3;
        if(tiny3tpu_hdmi_submit(coordinates,JAX_VERTEX_COUNT,phase))return 4;
        *(volatile uint32_t *)(uintptr_t)0x20002004U=0xBA000000U|phase;
        if((held&16U)&&!(held&32U))phase=(phase-speed)&255;
        else if((held&32U)&&!(held&16U))phase=(phase+speed)&255;
        else if(!paused && !((held&16U)&&(held&32U)))phase=(phase+speed)&255;
    }
}
