#!/usr/bin/env python3
"""Check freestanding binary32 math independently against the host math library."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <float.h>
#include <math.h>
#include <stdio.h>
#include "tiny3tpu_program_math.h"
static uint32_t bits(float x){union {float f;uint32_t u;} v={x};return v.u;}
static uint32_t random_state=0x73617274U;
static uint32_t random_word(void){
 random_state^=random_state<<13;random_state^=random_state>>17;
 random_state^=random_state<<5;return random_state;
}
static int check_sqrt(uint32_t input){
 float x=t3p_f32(input),actual=t3p_sqrt(x),expected=sqrtf(x);
 if(bits(actual)==bits(expected)||(isnan(actual)&&isnan(expected)))return 0;
 fprintf(stderr,"sqrt(%08x): %08x != %08x\n",input,bits(actual),bits(expected));return 1;
}
int main(void){
 /* Every normal significand for both exponent parities covers every
  * restoring-root input; every subnormal also checks normalization. */
 for(uint32_t m=0;m<0x800000U;m++){
  if(check_sqrt(0x3f800000U|m)||check_sqrt(0x40000000U|m)||check_sqrt(m))return 1;
 }
 /* Check exponent packing across all normal exponents and their edges. */
 for(uint32_t e=1;e<255;e++){
  if(check_sqrt(e<<23)||check_sqrt((e<<23)|1U)||check_sqrt((e<<23)|0x7fffffU))return 1;
 }
 const uint32_t special[]={0,0x80000000U,0x7f800000U,0xff800000U,0x7fc12345U,
                           0xffc12345U,0x7f812345U,0xff812345U,0xbf800000U};
 for(unsigned i=0;i<sizeof(special)/sizeof(*special);i++)if(check_sqrt(special[i]))return 1;
 if(bits(t3p_sin(-0.f))!=0x80000000U||bits(t3p_cos(-0.f))!=0x3f800000U)return 2;
 if(!isnan(t3p_sin(INFINITY))||!isnan(t3p_cos(-INFINITY)))return 2;
 float worst_trig=0.f,worst_atan=0.f;
 for(unsigned i=0;i<1000000;i++){
  uint32_t u=random_word();float x=t3p_f32(u);
  if(check_sqrt(u&0x7fffffffU))return 1;
  if(isfinite(x)){
   float s=t3p_sin(x),c=t3p_cos(x);
   float se=fabsf(s-(float)sin((double)x)),ce=fabsf(c-(float)cos((double)x));
   if(se>worst_trig)worst_trig=se;if(ce>worst_trig)worst_trig=ce;
   if(se>1.5e-7f||ce>1.5e-7f){fprintf(stderr,"trig(%08x): %g, %g\n",u,se,ce);return 2;}
   float a=fabsf(x),ae=fabsf(t3p_atan(a)-atanf(a));
   if(ae>worst_atan)worst_atan=ae;
   if(ae>2.4e-7f){fprintf(stderr,"atan(%08x): %g\n",u,ae);return 3;}
  }
 }
 printf("PASS 25165824 exhaustive sqrt cases, exponent edges, special values and "
        "1000000 seeded samples; max trig error=%g, max atan error=%g\n",worst_trig,worst_atan);
 return 0;
}
'''

LEGACY_HARNESS = r'''
#include <math.h>
#include <stdio.h>
#include "tiny3tpu_program_math.h"
int main(void){
 /* Frozen results from the previous five-iteration Newton implementation,
  * including cases that differ from correctly rounded sqrt by one ULP. */
 const uint32_t vectors[][2]={
  {0x00000000U,0x00000000U},{0x80000000U,0x80000000U},
  {0x00000001U,0x1a3504f3U},{0x00000002U,0x1a800000U},
  {0x00000003U,0x1a9cc470U},{0x007fffffU,0x1fffffffU},
  {0x00800000U,0x20000000U},{0x3eaaaaabU,0x3f13cd3aU},
  {0x3f800000U,0x3f800000U},{0x40000000U,0x3fb504f3U},
  {0x40400000U,0x3fddb3d8U},{0x40800000U,0x40000000U},
  {0x7f7fffffU,0x5f800000U},{0x3f800002U,0x3f800001U},
  {0x40000002U,0x3fb504f4U},{0x7f800000U,0x7f800000U}};
 for(unsigned i=0;i<sizeof(vectors)/sizeof(*vectors);i++){
  union {float f;uint32_t u;} v={t3p_sqrt(t3p_f32(vectors[i][0]))};
  if(v.u!=vectors[i][1]){fprintf(stderr,"legacy sqrt(%08x): %08x != %08x\n",
                                vectors[i][0],v.u,vectors[i][1]);return 1;}
 }
 if(!isnan(t3p_sqrt(-1.f))||!isnan(t3p_sqrt(-INFINITY))||!isnan(t3p_sqrt(NAN)))return 1;
 puts("PASS legacy sqrt compatibility vectors");return 0;
}
'''


class ProgramMathTests(unittest.TestCase):
    def compile_and_run(self, source, flags=()):
        with tempfile.TemporaryDirectory(prefix='tiny3tpu-math-') as directory:
            root = Path(directory)
            (root/'math.c').write_text(source)
            subprocess.run(['cc', '-std=c11', '-O2', '-ffp-contract=off', *flags,
                            '-I'+str(ROOT/'include'), str(root/'math.c'), '-lm',
                            '-o', str(root/'math')], check=True)
            subprocess.run([str(root/'math')], check=True)

    def test_binary32_math(self):
        self.compile_and_run(HARNESS)

    def test_legacy_sqrt_compatibility(self):
        self.compile_and_run(LEGACY_HARNESS, ['-DTINY3TPU_LEGACY_SQRT=1'])


if __name__ == '__main__':
    unittest.main()
