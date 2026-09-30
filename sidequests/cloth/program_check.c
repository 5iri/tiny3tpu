#include "cloth_program.h"
static t3p_workspace workspace;
static uint32_t calls;
static int reference_gemm(void *user,const int8_t *a,const int8_t *b,int32_t *out,uint32_t m,uint32_t k,uint32_t n){
 (void)user;calls++;
 for(uint32_t i=0;i<m;i++)for(uint32_t j=0;j<n;j++){
  int32_t sum=0;for(uint32_t t=0;t<k;t++)sum+=(int32_t)a[i*k+t]*b[t*n+j];out[i*n+j]=sum;
 }return 0;
}
static tiny3tpu_qgemm_backend backend={0,reference_gemm};
int program_step_float(const float *input,float *output){
 const void *inputs[]={input};void *outputs[]={output};
 return t3p_run(inputs,outputs,&workspace,&backend);
}
/* Persistent state and iteration count belong to the application, not the compiler. */
int program_advance_float(float *state,uint32_t steps){
 for(uint32_t i=0;i<steps;i++) {
  int status=program_step_float(state,state);if(status)return status;
 }
 return 0;
}
uint32_t program_backend_calls(void){return calls;}
