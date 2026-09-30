/* Generic application shell: input fixtures + generated inference functions.
 * IFQ1: sequence, mode, repetition count. IFR1: sequence, signed status,
 * total cycles, TPU calls, output words, XOR checksum, float32 output words.
 * All model operations, including CORDIC exponential, execute on board. */
#include <stddef.h>
#include <stdint.h>
#include "mlp.h"
#include "attention_sw.h"
#include "attention_hw.h"
#include "banana.h"
#include "fixture.h"
#include "tiny3tpu_axis_mailbox.h"
#include "tiny3tpu_mmio_backend.h"
#define UART ((volatile uint32_t *)(uintptr_t)0x20000000U)
static union {mlp_workspace mlp;attention_sw_workspace sw;attention_hw_workspace hw;banana_workspace banana;} work;
static float result[BANANA_OUTPUT_0_ELEMENTS];
static float banana_angle[1];
static uint32_t calls;
void *memcpy(void *d,const void *s,size_t n){unsigned char *a=d;const unsigned char *b=s;for(size_t i=0;i<n;i++)a[i]=b[i];return d;}
void *memset(void *d,int x,size_t n){unsigned char *a=d;for(size_t i=0;i<n;i++)a[i]=(unsigned char)x;return d;}
static int rd(void *u,uint32_t a,uint32_t *v){(void)u;__asm__ volatile("fence iorw, iorw":::"memory");*v=*(volatile uint32_t *)(uintptr_t)(0x20001000U+a);__asm__ volatile("fence iorw, iorw":::"memory");return 0;}
static int wr(void *u,uint32_t a,uint32_t v){(void)u;__asm__ volatile("fence iorw, iorw":::"memory");*(volatile uint32_t *)(uintptr_t)(0x20001000U+a)=v;__asm__ volatile("fence iorw, iorw":::"memory");return 0;}
static int gemm(void *u,const int8_t *a,const int8_t *b,int32_t *c,uint32_t m,uint32_t k,uint32_t n){calls++;return tiny3tpu_mmio_qgemm(u,a,b,c,m,k,n);}
static unsigned get_byte(void){while(!(UART[5]&1)){}return UART[0]&255;}
static void put_byte(unsigned v){while(!(UART[5]&32)){}UART[0]=v&255;}
static uint32_t get_word(void){uint32_t v=0;for(unsigned i=0;i<4;i++)v|=get_byte()<<(8*i);return v;}
static void put_word(uint32_t v){for(unsigned i=0;i<4;i++)put_byte(v>>(8*i));}
static uint32_t cycles(void){return *(volatile uint32_t *)(uintptr_t)0x20002008U;}
int main(void){
 UART[3]=0x83;UART[0]=108;UART[1]=0;UART[3]=3;UART[2]=7;
 tiny3tpu_axis_mailbox mailbox;if(tiny3tpu_axis_mailbox_init(&mailbox,0,rd,wr,1000))return 1;
 tiny3tpu_mmio io={&mailbox,tiny3tpu_axis_mailbox_read32,tiny3tpu_axis_mailbox_write32,1000};tiny3tpu_qgemm_backend backend={&io,gemm};
 const char *banner="INFERENCE CPU+TPU+CORDIC 100MHz 921600\n";while(*banner)put_byte(*banner++);
 for(;;){
  uint32_t sync=0;while(sync!=0x31514649U)sync=(sync>>8)|(get_byte()<<24);
  uint32_t seq=get_word(),mode=get_word(),repeats=get_word();int status=0;calls=0;
  uint32_t words=mode==0?20:mode==3?BANANA_OUTPUT_0_ELEMENTS:64;if(mode>3||repeats<1||repeats>100){status=-1;words=0;}
  const void *inputs[]={mode==0?input_0:mode==3?banana_angle:input_1};void *outputs[]={result};uint32_t start=cycles();
  for(uint32_t i=0;i<repeats&&!status;i++){
   status=mode==0?mlp_run(inputs,outputs,&work.mlp,&backend):mode==1?attention_sw_run(inputs,outputs,&work.sw,&backend):mode==2?attention_hw_run(inputs,outputs,&work.hw,&backend):banana_run(inputs,outputs,&work.banana,&backend);
   if(mode==3&&!status)banana_angle[0]=result[0];
  }
  uint32_t elapsed=cycles()-start,checksum=0;if(status)words=0;
  for(uint32_t i=0;i<words;i++){union{float f;uint32_t u;} v={result[i]};checksum^=v.u;}
  put_word(0x31524649U);put_word(seq);put_word(status);put_word(elapsed);put_word(calls);put_word(words);put_word(checksum);
  for(uint32_t i=0;i<words;i++){union{float f;uint32_t u;} v={result[i]};put_word(v.u);}
 }
}
