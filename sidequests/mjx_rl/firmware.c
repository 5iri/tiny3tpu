/* Autonomous compiled MJX + learner -> TPU -> CPU RGB565 -> HDMI. */
#include <stddef.h>
#include <stdint.h>
#include "mjx_tick.h"
#include "mjx_pose.h"
#include "renderer.h"
#include "training_config.h"
#include "tiny3tpu_mmio_backend.h"
#include "tiny3tpu_framebuffer.h"
static mjx_tick_workspace workspace;
static float state[20]=INITIAL_STATE,next_state[20];
static uint32_t pixels[TINY3TPU_FB_WORDS];
void *memcpy(void *d,const void *s,size_t n){unsigned char *a=d;const unsigned char *b=s;for(size_t i=0;i<n;i++)a[i]=b[i];return d;}
void *memset(void *d,int x,size_t n){unsigned char *a=d;for(size_t i=0;i<n;i++)a[i]=(unsigned char)x;return d;}
static int rd(void *u,uint32_t a,uint32_t *v){(void)u;*v=*(volatile uint32_t *)(uintptr_t)(0x20001000U+a);return 0;}
static int wr(void *u,uint32_t a,uint32_t v){(void)u;*(volatile uint32_t *)(uintptr_t)(0x20001000U+a)=v;return 0;}
static mjx_pose_workspace pose_workspace;
static float poses[12];
_Noreturn void port_fail(const char *message){
    unsigned hash=2166136261U;
    while(*message)hash=(hash^(unsigned char)*message++)*16777619U;
    *(volatile uint32_t *)(uintptr_t)0x20002000U=hash;
    for(;;){}
}
static void render(void){
    const void *inputs[]={state+6};void *outputs[]={poses};
    if(mjx_pose_run(inputs,outputs,&pose_workspace,0))port_fail("MJX kinematics");
    mujoco_renderer_draw(poses);
}
static int present(unsigned tag){
    render();
    int status;
    do{status=tiny3tpu_fb_present(pixels,TINY3TPU_FB_WORDS,tag);}while(status==1);
    if(status)return status;
    *(volatile uint32_t *)(uintptr_t)0x20002004U=tag;
    return 0;
}
int main(void){
    tiny3tpu_mmio io={0,rd,wr,1000};
    tiny3tpu_qgemm_backend backend={&io,tiny3tpu_mmio_qgemm,tiny3tpu_mmio_qgemm_packed,0};
    const void *inputs[]={state};void *outputs[]={next_state};
    unsigned ticks=0,frame=0;
    if(tiny3tpu_fb_check())return 1;
    if(tiny3tpu_fb_read(0x28)!=DISPLAY_WIDTH || tiny3tpu_fb_read(0x2c)!=DISPLAY_HEIGHT ||
       tiny3tpu_fb_read(0x30)!=DISPLAY_CLOCK_HZ)return 4;
    mujoco_renderer_init((uint16_t *)pixels,TINY3TPU_FB_WIDTH,TINY3TPU_FB_HEIGHT);
    if(present(frame++))return 1;
    for(;;){
        if(mjx_tick_run(inputs,outputs,&workspace,&backend))return 2;
#if VERIFY_TICKS
        for(unsigned i=0;i<20;i++){
            union{float f;uint32_t u;} actual={next_state[i]};
            if(actual.u!=expected_states[ticks][i])return 100+(int)i;
        }
#endif
        memcpy(state,next_state,sizeof(state));ticks++;
        if(ticks%8==0 && present(frame++))return 3;
#if VERIFY_TICKS
        if(ticks==VERIFY_TICKS)for(;;){} /* Keep scanout running for verification. */
#endif
    }
}
