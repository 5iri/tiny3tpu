/* Generic application shell: input fixtures + generated inference functions.
 * IFQ1: sequence, mode, repetition count. IFR1: sequence, signed status,
 * total cycles, TPU calls, output words, XOR checksum, float32 output words.
 * All model operations, including CORDIC exponential, execute on board. */
#include <stddef.h>
#include <stdint.h>
#include "classifier.h"
#include "digits.h"
#include "tiny3tpu_axis_mailbox.h"
#include "tiny3tpu_mmio_backend.h"
#define TINY3TPU_MAX_RESPONSE_BYTES 72U
#include "tiny3tpu_demo_transport.h"
static classifier_workspace work;
static float result[11];

static uint32_t calls;
void *memcpy(void *d,const void *s,size_t n){unsigned char *a=d;const unsigned char *b=s;for(size_t i=0;i<n;i++)a[i]=b[i];return d;}
void *memset(void *d,int x,size_t n){unsigned char *a=d;for(size_t i=0;i<n;i++)a[i]=(unsigned char)x;return d;}
static int rd(void *u,uint32_t a,uint32_t *v){(void)u;__asm__ volatile("fence iorw, iorw":::"memory");*v=*(volatile uint32_t *)(uintptr_t)(0x20001000U+a);__asm__ volatile("fence iorw, iorw":::"memory");return 0;}
static int wr(void *u,uint32_t a,uint32_t v){(void)u;__asm__ volatile("fence iorw, iorw":::"memory");*(volatile uint32_t *)(uintptr_t)(0x20001000U+a)=v;__asm__ volatile("fence iorw, iorw":::"memory");return 0;}
static int gemm(void *u,const int8_t *a,const int8_t *b,int32_t *c,uint32_t m,uint32_t k,uint32_t n){calls++;return tiny3tpu_mmio_qgemm(u,a,b,c,m,k,n);}
static int gemm_packed(void *u,const int8_t *a,const int8_t *b,const uint32_t *pa,const uint32_t *pb,int32_t *c,uint32_t m,uint32_t k,uint32_t n){calls++;return tiny3tpu_mmio_qgemm_packed(u,a,b,pa,pb,c,m,k,n);}
static int gemm_kernel(void *u,tiny3tpu_mmio_kernel kernel,void *context){int status=tiny3tpu_mmio_run_kernel(u,kernel,context);if(status!=TINY3TPU_MMIO_KERNEL_UNSUPPORTED)calls++;return status;}
static unsigned get_byte(void){return tiny3tpu_demo_get_byte();}
static uint32_t get_word(void){uint32_t v=0;for(unsigned i=0;i<4;i++)v|=get_byte()<<(8*i);return v;}
static void put_word(uint32_t v){tiny3tpu_demo_put_word(v);}
static uint32_t cycles(void){return *(volatile uint32_t *)(uintptr_t)0x20002008U;}
int main(void){
 if(tiny3tpu_demo_init())return 1;
#if TINY3TPU_DIRECT_TPU
 tiny3tpu_mmio io={0,rd,wr,1000};
#else
 tiny3tpu_axis_mailbox mailbox;if(tiny3tpu_axis_mailbox_init(&mailbox,0,rd,wr,1000))return 1;
 tiny3tpu_mmio io={&mailbox,tiny3tpu_axis_mailbox_read32,tiny3tpu_axis_mailbox_write32,1000};
#endif
 tiny3tpu_qgemm_backend backend={&io,gemm,gemm_packed,gemm_kernel};
 tiny3tpu_demo_banner("TRAINED MNIST CPU+TPU 100MHz 921600\n");
 for(;;){
  tiny3tpu_demo_begin(0x31514649U,16U);
  uint32_t sync=0;while(sync!=0x31514649U)sync=(sync>>8)|(get_byte()<<24);
  uint32_t seq=get_word(),mode=get_word(),repeats=get_word();int status=0;calls=0;
  uint32_t words=11;if(mode>=20||repeats<1||repeats>100){status=-1;words=0;}
  const void *inputs[]={digit_inputs[mode<20?mode:0]};void *outputs[]={result};uint32_t start=cycles();
  for(uint32_t i=0;i<repeats&&!status;i++)status=classifier_run(inputs,outputs,&work,&backend);
  if(!status){unsigned best=0;for(unsigned i=1;i<10;i++)if(result[i]>result[best])best=i;result[10]=(float)best;}
  uint32_t elapsed=cycles()-start,checksum=0;if(status)words=0;
  for(uint32_t i=0;i<words;i++){union{float f;uint32_t u;} v={result[i]};checksum^=v.u;}
  put_word(0x31524649U);put_word(seq);put_word(status);put_word(elapsed);put_word(calls);put_word(words);put_word(checksum);
  for(uint32_t i=0;i<words;i++){union{float f;uint32_t u;} v={result[i]};put_word(v.u);}
  tiny3tpu_demo_end();
 }
}
