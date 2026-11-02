/* No rasterizer commands: compiled JAX -> generic TPU driver -> CPU pixels. */
#include <stddef.h>
#include <stdint.h>
#include "pixels_program.h"
#include "tiny3tpu_mmio_backend.h"
#include "tiny3tpu_framebuffer.h"
static pixels_program_workspace workspace;
static uint32_t pixels[TINY3TPU_FB_WORDS];
static int32_t phase[1],coordinates[16];
static unsigned backend_calls;
void *memcpy(void *d,const void *s,size_t n){unsigned char *a=d;const unsigned char *b=s;for(size_t i=0;i<n;i++)a[i]=b[i];return d;}
void *memset(void *d,int x,size_t n){unsigned char *a=d;for(size_t i=0;i<n;i++)a[i]=(unsigned char)x;return d;}
static int rd(void *u,uint32_t a,uint32_t *v){(void)u;*v=*(volatile uint32_t *)(uintptr_t)(0x20001000U+a);return 0;}
static int wr(void *u,uint32_t a,uint32_t v){(void)u;*(volatile uint32_t *)(uintptr_t)(0x20001000U+a)=v;return 0;}
static int gemm(void *u,const int8_t *a,const int8_t *b,int32_t *c,uint32_t m,uint32_t k,uint32_t n){
    backend_calls++;return tiny3tpu_mmio_qgemm(u,a,b,c,m,k,n);
}
static int packed(void *u,const int8_t *a,const int8_t *b,const uint32_t *pa,const uint32_t *pb,int32_t *c,uint32_t m,uint32_t k,uint32_t n){
    backend_calls++;return tiny3tpu_mmio_qgemm_packed(u,a,b,pa,pb,c,m,k,n);
}
static void put_pixel(int x,int y,uint16_t rgb){
    if(x<0 || x>=160 || y<0 || y>=120)return;
    unsigned i=(unsigned)y*160U+(unsigned)x,shift=(i&1U)*16U;
    pixels[i/2]=(pixels[i/2]&~(UINT32_C(0xffff)<<shift))|((uint32_t)rgb<<shift);
}
static void line(int x,int y,int tx,int ty,uint16_t color){
    int dx=tx>x ? tx-x : x-tx,sx=x<tx ? 1 : -1;
    int dy=ty>y ? y-ty : ty-y,sy=y<ty ? 1 : -1,error=dx+dy;
    for(;;){
        put_pixel(x,y,color);if(x==tx && y==ty)break;
        int twice=2*error;
        if(twice>=dy){error+=dy;x+=sx;}
        if(twice<=dx){error+=dx;y+=sy;}
    }
}
int main(void){
    tiny3tpu_mmio io={0,rd,wr,1000};
    tiny3tpu_qgemm_backend backend={&io,gemm,packed,0};
    const void *inputs[]={phase};void *outputs[]={coordinates};
    if(tiny3tpu_fb_check())return 1;
    for(;;){
        backend_calls=0;
        if(pixels_program_run(inputs,outputs,&workspace,&backend) || backend_calls!=1)return 2;
        for(unsigned i=0;i<TINY3TPU_FB_WORDS;i++)pixels[i]=UINT32_C(0x08410841);
        for(unsigned i=0;i<8;i++){
            unsigned j=(i&4U)|((i+1U)&3U);
            line(80+coordinates[i*2]/64,60+coordinates[i*2+1]/64,
                 80+coordinates[j*2]/64,60+coordinates[j*2+1]/64,i<4 ? 0xffe0 : 0x07ff);
        }
        int status;
        do{status=tiny3tpu_fb_present(pixels,TINY3TPU_FB_WORDS,(uint32_t)phase[0]);}while(status==1);
        if(status)return 3;
        *(volatile uint32_t *)(uintptr_t)0x20002004U=(uint32_t)phase[0];
        phase[0]=(phase[0]+1)&63;
    }
}
