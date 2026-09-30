/* JAX-exported int8 matmul+bias, executed by RV32IM runtime and AXI DMA TPU. */
#include "tiny3tpu_runtime.h"
#include "tiny3tpu_dma.h"
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "jax_demo_model.h"
int synapse32_dram_initialize(void);
static unsigned launches;
static tiny3tpu_dma dma = {
    (volatile uint32_t *)(uintptr_t)0x20003000,
    (volatile uint32_t *)(uintptr_t)0x40020000,
    (volatile uint32_t *)(uintptr_t)0x40022000, 256, 100000, 0
};
void *memset(void *dest, int value, size_t size)
{
    unsigned char *p=dest;
    for(size_t i=0;i<size;++i) p[i]=(unsigned char)value;
    return dest;
}
static int run_tpu(void *user, const int8_t *a, const int8_t *b,
                   int32_t *out, uint32_t m, uint32_t k, uint32_t n)
{
    ++launches;
    printf("TPU DMA launch %u: M=%u K=%u N=%u\n", launches,m,k,n);
    return tiny3tpu_dma_qgemm(user,a,b,out,m,k,n);
}
int main(void)
{
    if(!synapse32_dram_initialize()) { puts("JAX FAIL: DDR initialization"); return 10; }
    puts("JAX demo: DDR initialization passed");
    uint8_t *model=(uint8_t *)(uintptr_t)0x40030000;
    int8_t *input=(int8_t *)(uintptr_t)0x40031000;
    uint8_t *workspace=(uint8_t *)(uintptr_t)0x40032000;
    memcpy(model,jax_model,sizeof(jax_model));
    memcpy(input,jax_input,sizeof(jax_input));
    if(tiny3tpu_dma_init(&dma)) { puts("JAX FAIL: DMA init"); return 12; }
    tiny3tpu_qgemm_backend backend={&dma,run_tpu};
    tiny3tpu_runtime runtime;
    int status=tiny3tpu_runtime_init(&runtime,&backend);
    if(!status) status=tiny3tpu_runtime_load_model(&runtime,model,sizeof(jax_model));
    if(!status) status=tiny3tpu_runtime_bind_workspace(&runtime,workspace,4096);
    if(!status) status=tiny3tpu_runtime_bind_input(&runtime,0,input,sizeof(jax_input));
    if(!status) status=tiny3tpu_runtime_run(&runtime);
    int32_t output[6];
    if(!status) status=tiny3tpu_runtime_read_output(&runtime,3,output,6);
    if(status) { printf("JAX FAIL: runtime status %d\n",status); return 20; }
    unsigned mismatch=0;
    for(unsigned i=0;i<6;++i) {
        printf("JAX output[%u]=%d expected=%d\n",i,output[i],jax_expected[i]);
        mismatch|=output[i]!=jax_expected[i];
    }
    if(mismatch || launches!=1) { puts("JAX FAIL: comparison or TPU call count");return 21; }
    puts("JAX PASS: Synapse32 + DDR3 + AXI DMA + TPU, all 6 outputs match JAX");
    return 0;
}
