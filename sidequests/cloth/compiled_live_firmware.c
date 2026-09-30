/* Application shell around the generic StableHLO compiler output.
 * Physics/state stay on the board; the host sends only step/reset commands.
 * CLQ3 bit 9 requests a diagnostic state snapshot for independent verification.
 */
#include <stddef.h>
#include <stdint.h>
#include "cloth_program.h"
#include "compiled_scene.h"
#include "tiny3tpu_axis_mailbox.h"
#include "tiny3tpu_mmio_backend.h"

#define UART ((volatile uint32_t *)(uintptr_t)0x20000000U)
#ifndef TINY3TPU_CLOCK_HZ
#define TINY3TPU_CLOCK_HZ 100000000
#endif
#define UART_DIVISOR ((TINY3TPU_CLOCK_HZ + 460800) / 921600 - 1)
_Static_assert(T3P_INPUT_0_ELEMENTS == 180 && T3P_OUTPUT_0_ELEMENTS == 180,
               "cloth application requires 30 position/velocity rows");
static t3p_workspace workspace;
static float state[T3P_INPUT_0_ELEMENTS];
static int8_t vertices[28 * 3];
static int32_t coordinates[28 * 3];
static uint32_t simulation_steps, backend_calls;

void *memcpy(void *d,const void *s,size_t n) {
    unsigned char *a=d;const unsigned char *b=s;
    for(size_t i=0;i<n;i++)a[i]=b[i];
    return d;
}
void *memset(void *d,int x,size_t n) {
    unsigned char *a=d;for(size_t i=0;i<n;i++)a[i]=(unsigned char)x;return d;
}
static int rd(void *u,uint32_t a,uint32_t *v) {
    (void)u;__asm__ volatile("fence iorw, iorw" ::: "memory");
    *v=*(volatile uint32_t *)(uintptr_t)(0x20001000U+a);
    __asm__ volatile("fence iorw, iorw" ::: "memory");return 0;
}
static int wr(void *u,uint32_t a,uint32_t v) {
    (void)u;__asm__ volatile("fence iorw, iorw" ::: "memory");
    *(volatile uint32_t *)(uintptr_t)(0x20001000U+a)=v;
    __asm__ volatile("fence iorw, iorw" ::: "memory");return 0;
}
static int gemm(void *u,const int8_t *a,const int8_t *b,int32_t *c,
                uint32_t m,uint32_t k,uint32_t n) {
    backend_calls++;
    return tiny3tpu_mmio_qgemm(u,a,b,c,m,k,n);
}
static unsigned get_byte(void) {while(!(UART[5]&1)){}return UART[0]&255;}
static void put_byte(unsigned v) {while(!(UART[5]&32)){}UART[0]=v&255;}
static uint32_t get_word(void) {
    uint32_t v=0;for(unsigned i=0;i<4;i++)v|=get_byte()<<(8*i);return v;
}
static void put_word(uint32_t v) {for(unsigned i=0;i<4;i++)put_byte(v>>(8*i));}
static uint32_t cycles(void) {return *(volatile uint32_t *)(uintptr_t)0x20002008U;}
int main(void) {
    UART[3]=0x83;UART[0]=UART_DIVISOR&255;UART[1]=UART_DIVISOR>>8;UART[3]=3;UART[2]=7;
    tiny3tpu_axis_mailbox mailbox;
    if(tiny3tpu_axis_mailbox_init(&mailbox,0,rd,wr,1000))return 1;
    tiny3tpu_mmio io={&mailbox,tiny3tpu_axis_mailbox_read32,tiny3tpu_axis_mailbox_write32,1000};
    tiny3tpu_qgemm_backend backend={&io,gemm};
    const void *inputs[]={state};void *outputs[]={state};
    memcpy(state,initial_state,sizeof(state));
    const char *banner="CLOTH STABLEHLO CPU+TPU 921600 noddr\n";
    while(*banner)put_byte((unsigned char)*banner++);
    for(;;) {
        uint32_t sync=0;
        while(sync!=0x33514c43U)sync=(sync>>8)|(get_byte()<<24);
        uint32_t sequence=get_word(),command=get_word();
        if(command&256){memcpy(state,initial_state,sizeof(state));simulation_steps=0;}
        unsigned steps=command&255;if(steps>32)steps=32;
        backend_calls=0;int status=0;uint32_t start=cycles();
        for(unsigned i=0;i<steps;i++) {
            status=t3p_run(inputs,outputs,&workspace,&backend);
            if(status)break;
            simulation_steps++;
        }
        uint32_t physics_cycles=cycles()-start,physics_calls=backend_calls;
        start=cycles();
        if(!status)for(unsigned i=0;i<28;i++)for(unsigned k=0;k<3;k++) {
            float v=state[i*6+k]*8.f;
            if(!(v>-127.f && v<127.f)){status=-2;break;}
            vertices[i*3+k]=(int8_t)(int)(v+(v<0?-.5f:.5f));
        }
        if(!status)status=gemm(&io,vertices,camera_weights,coordinates,28,3,3);
        uint32_t checksum=0;
        if(!status)for(unsigned i=0;i<84;i++) {
            coordinates[i]+=camera_bias[i%3];checksum^=(uint32_t)coordinates[i];
        }
        uint32_t transform_cycles=cycles()-start;
        put_word(0x33524c43U);put_word(sequence);put_word((uint32_t)status);
        put_word(transform_cycles);put_word(status?0:28);put_word(checksum);
        put_word(physics_cycles);put_word(simulation_steps);put_word(physics_calls);
        if(!status)for(unsigned i=0;i<84;i++)put_word((uint32_t)coordinates[i]);
        if(!status && (command&512))for(unsigned i=0;i<T3P_OUTPUT_0_ELEMENTS;i++) {
            union {float f;uint32_t u;} value={state[i]};put_word(value.u);
        }
    }
}
