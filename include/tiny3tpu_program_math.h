#ifndef TINY3TPU_PROGRAM_MATH_H
#define TINY3TPU_PROGRAM_MATH_H
#include <stdint.h>
static inline float t3p_f32(uint32_t x) {union {uint32_t u;float f;} v={x};return v.f;}
static inline uint32_t t3p_u32_bits(float x) {union {float f;uint32_t u;} v={x};return v.u;}
static inline float t3p_fneg(float x) {return t3p_f32(t3p_u32_bits(x)^0x80000000U);}
static inline float t3p_fabs(float x) {return t3p_f32(t3p_u32_bits(x)&0x7fffffffU);}
/* Freestanding float32 CPU fallback; no host runtime or allocation. */
static inline int t3p_finite(float x) { return (t3p_u32_bits(x)&0x7f800000U)!=0x7f800000U; }
static inline int t3p_feq(float a,float b) {
 uint32_t ua=t3p_u32_bits(a),ub=t3p_u32_bits(b),aa=ua&0x7fffffffU,ab=ub&0x7fffffffU;
 return aa<=0x7f800000U&&ab<=0x7f800000U&&(ua==ub||((aa|ab)==0U));
}
static inline int t3p_fne(float a,float b) {return !t3p_feq(a,b);}
static inline int t3p_flt(float a,float b) {
 uint32_t ua=t3p_u32_bits(a),ub=t3p_u32_bits(b),aa=ua&0x7fffffffU,ab=ub&0x7fffffffU;
 if(aa>0x7f800000U||ab>0x7f800000U||((aa|ab)==0U))return 0;
 int32_t ka=(int32_t)(ua^((uint32_t)((int32_t)ua>>31)&0x7fffffffU));
 int32_t kb=(int32_t)(ub^((uint32_t)((int32_t)ub>>31)&0x7fffffffU));
 return ka<kb;
}
static inline int t3p_fle(float a,float b) {
 uint32_t ua=t3p_u32_bits(a),ub=t3p_u32_bits(b),aa=ua&0x7fffffffU,ab=ub&0x7fffffffU;
 if(aa>0x7f800000U||ab>0x7f800000U)return 0;
 if((aa|ab)==0U)return 1;
 int32_t ka=(int32_t)(ua^((uint32_t)((int32_t)ua>>31)&0x7fffffffU));
 int32_t kb=(int32_t)(ub^((uint32_t)((int32_t)ub>>31)&0x7fffffffU));
 return ka<=kb;
}
static inline int t3p_fgt(float a,float b) {return t3p_flt(b,a);}
static inline int t3p_fge(float a,float b) {return t3p_fle(b,a);}
/* Hardware MMIO FPU & Quantization unit at 0x20003040 (enabled by default on
 * RV32IM VexRiscv targets without hardware F extension). */
#ifndef TINY3TPU_FPU_MMIO
#if defined(__riscv) && defined(__riscv_mul) && !defined(__riscv_flen)
#define TINY3TPU_FPU_MMIO 1
#else
#define TINY3TPU_FPU_MMIO 0
#endif
#endif
#define TINY3TPU_FPU_BASE 0x20003040U
#define TINY3TPU_FPU_REG_F32(off) (*(volatile float *)(uintptr_t)(TINY3TPU_FPU_BASE+(off)))
#define TINY3TPU_FPU_REG_U32(off) (*(volatile uint32_t *)(uintptr_t)(TINY3TPU_FPU_BASE+(off)))
#define TINY3TPU_FPU_REG_I32(off) (*(volatile int32_t *)(uintptr_t)(TINY3TPU_FPU_BASE+(off)))
static inline float t3p_fadd(float a,float b) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=a;TINY3TPU_FPU_REG_F32(0x04U)=b;
 return TINY3TPU_FPU_REG_F32(0x08U);
#else
 return a+b;
#endif
}
static inline float t3p_fsub(float a,float b) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=a;TINY3TPU_FPU_REG_F32(0x04U)=b;
 return TINY3TPU_FPU_REG_F32(0x0CU);
#else
 return a-b;
#endif
}
static inline float t3p_fmul(float a,float b) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=a;TINY3TPU_FPU_REG_F32(0x04U)=b;
 return TINY3TPU_FPU_REG_F32(0x10U);
#else
 return a*b;
#endif
}
static inline float t3p_i32_to_f32(int32_t x) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_I32(0x00U)=x;
 return TINY3TPU_FPU_REG_F32(0x14U);
#else
 return (float)x;
#endif
}
static inline float t3p_u32_to_f32(uint32_t x) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_U32(0x00U)=x;
 return TINY3TPU_FPU_REG_F32(0x18U);
#else
 return (float)x;
#endif
}
/* Exact binary32 floor, including subnormals, signed zero and infinities. */
static inline float t3p_floor(float x) {
 union {float f;uint32_t u;} v={x};uint32_t magnitude=v.u&0x7fffffffU;
 int exponent=(int)(magnitude>>23)-127;
 if(exponent>=23 || magnitude==0)return x;
 if(exponent<0)return v.u>>31 ? -1.f : 0.f;
 uint32_t mask=(UINT32_C(1)<<(23-exponent))-1;
 if(!(v.u&mask))return x;
 v.u&=~mask;return (v.u>>31) ? t3p_fsub(v.f,1.f) : v.f;
}
/* Default sqrt is correctly rounded binary32 (nearest, ties to even).
 * Define TINY3TPU_LEGACY_SQRT=1 when reproducing old firmware trajectories:
 * its five rounded Newton steps can differ from the correct result by 1 ULP.
 * That difference can grow in long-running, sensitive physical simulations. */
#ifndef TINY3TPU_LEGACY_SQRT
#define TINY3TPU_LEGACY_SQRT 0
#endif
static inline float t3p_sqrt(float x) {
#if TINY3TPU_LEGACY_SQRT
 if(x==0)return x;
 if(!t3p_finite(x))return x>0?x:x-x;
 if(x<0)return t3p_f32(0x7fc00000U);
 int subnormal=x<0x1p-126f;if(subnormal)x*=0x1p24f;
 union {float f;uint32_t u;} v={x};v.u=(v.u>>1)+0x1fc00000U;
 float r=v.f;for(unsigned i=0;i<5;i++)r=.5f*(r+x/r);return subnormal?r*0x1p-12f:r;
#else
 union {float f;uint32_t u;} v={x};uint32_t ax=v.u&0x7fffffffU;
 if(!ax)return x;
 if(ax>=0x7f800000U)return (ax>0x7f800000U||(v.u>>31))?t3p_f32(0x7fc00000U):x;
 if(v.u>>31)return t3p_f32(0x7fc00000U);
 int exponent=(int)(ax>>23)-127;uint32_t mantissa=ax&0x7fffffU;
 if(ax>>23)mantissa|=0x800000U;
 else {exponent=-126;while(mantissa<0x800000U){mantissa<<=1;exponent--;}}
 if(exponent%2){mantissa<<=1;exponent--;}
 /* Restore sqrt(mantissa * 2^23), consuming two radicand bits per step.
  * Its low 23 bits are zero, so a 32-bit shift register holds all of the
  * nonzero input bits. Remainder and trial stay below 2^26. This avoids
  * software float division and works for subnormal inputs without scaling.
  * For integer remainder R and floor root Q, rounding up requires R > Q:
  * (Q + 1/2)^2 = Q^2 + Q + 1/4, so a midpoint tie cannot occur. */
 uint32_t bits=mantissa<<7,root=0,remainder=0;
 for(unsigned i=0;i<24;i++){
  remainder=(remainder<<2)|(bits>>30);bits<<=2;
  uint32_t trial=(root<<2)|1U;root<<=1;
  if(remainder>=trial){remainder-=trial;root|=1U;}
 }
 root+=remainder>root;
 return t3p_f32(((uint32_t)(exponent/2+126)<<23)+root);
#endif
}
static inline int32_t t3p_to_int32(float x);
static inline float t3p_div(float a,float b);
/* Explicit freestanding exponential approximation. Reduce to +/- ln(2)/2,
 * evaluate a degree-7 Taylor polynomial, then scale by a power of two.
 * Split ln(2) reduces cancellation; subnormal scaling avoids bit tricks on
 * negative exponents. NaN/infinities and overflow/underflow are handled first. */
static inline float t3p_exp(float x) {
 uint32_t ux=t3p_u32_bits(x),ax=ux&0x7fffffffU;
 if(ax>0x7f800000U)return t3p_f32(ux|0x00400000U);
 if(t3p_fgt(x,0x1.62e42ep6f))return t3p_f32(0x7f800000U);
 if(t3p_flt(x,-0x1.9fe368p6f))return 0.f;
 float scaled=t3p_fmul(x,0x1.715476p0f);
 int n=(int)t3p_to_int32(t3p_fadd(scaled,(ux>>31)?-.5f:.5f));
 float fn=t3p_i32_to_f32(n);
 float r=t3p_fsub(t3p_fsub(x,t3p_fmul(fn,0x1.62e400p-1f)),t3p_fmul(fn,0x1.7f7d1cp-20f));
 float p=t3p_fadd(1.f/720.f,t3p_fmul(r,1.f/5040.f));
 p=t3p_fadd(1.f/120.f,t3p_fmul(r,p));
 p=t3p_fadd(1.f/24.f,t3p_fmul(r,p));
 p=t3p_fadd(1.f/6.f,t3p_fmul(r,p));
 p=t3p_fadd(.5f,t3p_fmul(r,p));
 p=t3p_fadd(1.f,t3p_fmul(r,p));
 float y=t3p_fadd(1.f,t3p_fmul(r,p));
 if(n>127)return t3p_fmul(t3p_fmul(y,2.f),0x1p127f);
 if(n< -126)return t3p_fmul(t3p_fmul(y,t3p_f32((uint32_t)(n+24+127)<<23)),0x1p-24f);
 return t3p_fmul(y,t3p_f32((uint32_t)(n+127)<<23));
}
static inline float t3p_atan(float x) {
 int inv=t3p_fgt(x,1.f);if(inv)x=t3p_div(1.f,x);
 int rotate=t3p_fgt(x,.414213562373095f);if(rotate)x=t3p_div(t3p_fsub(x,1.f),t3p_fadd(x,1.f));
 static const float coefficients[]={1.f/17.f,1.f/15.f,1.f/13.f,1.f/11.f,
                                    1.f/9.f,1.f/7.f,1.f/5.f,1.f/3.f,1.f};
 float xx=t3p_fmul(x,x),sum=1.f/19.f;
 for(unsigned i=0;i<9;i++)sum=t3p_fsub(coefficients[i],t3p_fmul(xx,sum));
 float r=t3p_fmul(x,sum);if(rotate)r=t3p_fadd(r,.7853981633974483f);
 return inv?t3p_fsub(1.5707963267948966f,r):r;
}
static inline float t3p_acos(float x) {
 if(t3p_feq(x,1.f))return 0.f;
 if(t3p_feq(x,-1.f))return 3.141592653589793f;
 if(t3p_flt(x,-1.f)||t3p_fgt(x,1.f))return t3p_sqrt(-1.f);
 float a=t3p_fabs(x);float r=t3p_fmul(2.f,t3p_atan(t3p_sqrt(t3p_div(t3p_fsub(1.f,a),t3p_fadd(1.f,a)))));
 return (t3p_u32_bits(x)>>31)?t3p_fsub(3.141592653589793f,r):r;
}
static inline float t3p_atan2(float y,float x) {
 union {float f;uint32_t u;} a={x},b={y};
 uint32_t ax=a.u&0x7fffffffU,ay=b.u&0x7fffffffU;
 int sx=(int)(a.u>>31),sy=(int)(b.u>>31);
 float r;
 if(ax>0x7f800000U||ay>0x7f800000U)return t3p_fadd(x,y);
 if(ay==0)return sx?(sy?-3.141592653589793f:3.141592653589793f):y;
 if(ax==0||ay==0x7f800000U) {
  r=ax==0x7f800000U?.7853981633974483f:1.5707963267948966f;
 } else if(ax==0x7f800000U)r=0.f;
 else {a.u=ax;b.u=ay;r=t3p_atan(t3p_div(b.f,a.f));}
 if(sx)r=t3p_fsub(3.141592653589793f,r);
 return sy?t3p_fneg(r):r;
}
/* Full binary32-domain argument reduction. 2/pi is stored as a 256-bit
 * fixed-point integer; its truncation contributes <2^-128 turns even at
 * FLT_MAX. No float-to-integer conversion of a huge angle is performed.
 * Pure 64-bit integer reduction avoids soft-double libgcc calls on RV32. */
static inline uint32_t t3p_bit(const uint32_t *words,unsigned bit) {
 return (words[bit/32]>>(bit%32))&1U;
}
static inline float t3p_sincos(float x,int cosine) {
 static const uint32_t two_over_pi[8]={0xdebbc561U,0xfe5163abU,0x3c439041U,0xdb629599U,
                                       0xf534ddc0U,0xfc2757d1U,0x4e441529U,0xa2f9836eU};
 union {float f;uint32_t u;} v={x};uint32_t ax=v.u&0x7fffffffU;unsigned sign=v.u>>31;
 if(ax>=0x7f800000U)return t3p_f32(0x7fc00000U);
 unsigned quadrant=0;float r;
 if(ax<=0x3f490fdbU){v.u=ax;r=v.f;}
 else {
  unsigned exponent=ax>>23,shift=406-exponent;
  uint32_t mantissa=(ax&0x7fffffU)|0x800000U,product[9];uint64_t carry=0;
  for(unsigned i=0;i<8;i++){uint64_t part=(uint64_t)two_over_pi[i]*mantissa+carry;product[i]=(uint32_t)part;carry=part>>32;}
  product[8]=(uint32_t)carry;
  quadrant=t3p_bit(product,shift)|(t3p_bit(product,shift+1)<<1);
  unsigned word=(shift-64)/32,offset=(shift-64)%32;
  uint64_t fraction=((uint64_t)product[word+1]<<32)|product[word];
  if(offset)fraction=(fraction>>offset)|((uint64_t)product[word+2]<<(64-offset));
  uint32_t r_sign=0U;
  if(fraction>>63){quadrant=(quadrant+1)&3U;fraction=0ULL-fraction;r_sign=0x80000000U;}
  int exp_r=126;
  while(!(fraction>>63)){fraction<<=1;exp_r--;}
  uint32_t f_hi=(uint32_t)(fraction>>32),f_lo=(uint32_t)fraction;
  uint64_t prod=(uint64_t)f_hi*0xc90fdaa2ULL+(((uint64_t)f_hi*0x2168c235ULL)>>32)+(((uint64_t)f_lo*0xc90fdaa2ULL)>>32);
  if(prod>>63)exp_r++; else prod<<=1;
  uint32_t mant=(uint32_t)(prod>>40);
  mant+=((prod>>39)&1U)&(((prod&0x7fffffffffULL)!=0ULL)|(mant&1U));
  if(mant>=0x1000000U){mant>>=1;exp_r++;}
  r=t3p_f32(r_sign|((uint32_t)exp_r<<23)|(mant&0x7fffffU));
 }
 if(cosine)quadrant=(quadrant+1)&3U;
 float z=t3p_fmul(r,r),result;
 if(quadrant&1U){
  float p=t3p_fadd(-1.f/3628800.f,t3p_fmul(z,1.f/479001600.f));
  p=t3p_fadd(1.f/40320.f,t3p_fmul(z,p));
  p=t3p_fadd(-1.f/720.f,t3p_fmul(z,p));
  p=t3p_fadd(1.f/24.f,t3p_fmul(z,p));
  p=t3p_fadd(-.5f,t3p_fmul(z,p));
  result=t3p_fadd(1.f,t3p_fmul(z,p));
 } else {
  float p=t3p_fadd(-1.f/39916800.f,t3p_fmul(z,1.f/6227020800.f));
  p=t3p_fadd(1.f/362880.f,t3p_fmul(z,p));
  p=t3p_fadd(-1.f/5040.f,t3p_fmul(z,p));
  p=t3p_fadd(1.f/120.f,t3p_fmul(z,p));
  p=t3p_fadd(-1.f/6.f,t3p_fmul(z,p));
  result=t3p_fadd(r,t3p_fmul(r,t3p_fmul(z,p)));
 }
 if(quadrant&2U)result=t3p_fneg(result);
 return !cosine&&sign?t3p_fneg(result):result;
}
static inline float t3p_sin(float x){return t3p_sincos(x,0);}
static inline float t3p_cos(float x){return t3p_sincos(x,1);}
/* Defined integer wrapping, including INT_MIN, without signed C overflow. */
static inline int32_t t3p_i32(uint32_t x) {
 return x<=INT32_MAX?(int32_t)x:(int32_t)((int64_t)x-INT64_C(4294967296));
}
static inline int32_t t3p_i8(uint32_t x) {
 x&=255U;return x<128U?(int32_t)x:(int32_t)x-256;
}
/* Saturating float-to-integer conversion; NaN maps to zero.
 * Pure integer IEEE-754 bit extraction or MMIO FPU avoids soft-float libgcc calls. */
static inline int32_t t3p_to_int32(float x) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=x;
 return TINY3TPU_FPU_REG_I32(0x1CU);
#else
 union {float f;uint32_t u;} v={x};
 uint32_t ax=v.u&0x7fffffffU,sign=v.u>>31;
 if(ax<0x3f800000U||ax>0x7f800000U)return 0;
 if(ax>=0x4f000000U)return sign?INT32_MIN:INT32_MAX;
 unsigned exp=(ax>>23)-127U;
 uint32_t mag=(ax&0x7fffffU)|0x800000U;
 mag=exp>=23U?(mag<<(exp-23U)):(mag>>(23U-exp));
 return sign?-(int32_t)mag:(int32_t)mag;
#endif
}
static inline uint32_t t3p_to_uint32(float x) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=x;
 return TINY3TPU_FPU_REG_U32(0x20U);
#else
 union {float f;uint32_t u;} v={x};
 uint32_t ax=v.u&0x7fffffffU,sign=v.u>>31;
 if(sign||ax<0x3f800000U||ax>0x7f800000U)return 0U;
 if(ax>=0x4f800000U)return UINT32_MAX;
 unsigned exp=(ax>>23)-127U;
 uint32_t mag=(ax&0x7fffffU)|0x800000U;
 return exp>=23U?(mag<<(exp-23U)):(mag>>(23U-exp));
#endif
}
static inline int8_t t3p_to_int8(float x) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=x;
 return (int8_t)TINY3TPU_FPU_REG_I32(0x24U);
#else
 union {float f;uint32_t u;} v={x};
 uint32_t ax=v.u&0x7fffffffU,sign=v.u>>31;
 if(ax<0x3f800000U||ax>0x7f800000U)return 0;
 if(!sign&&ax>=0x42fe0000U)return 127;
 if(sign&&ax>=0x43000000U)return -128;
 int32_t mag=(int32_t)(((ax&0x7fffffU)|0x800000U)>>(150U-(ax>>23)));
 return (int8_t)(sign?-mag:mag);
#endif
}
static inline uint8_t t3p_to_uint8(float x) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=x;
 return (uint8_t)TINY3TPU_FPU_REG_U32(0x28U);
#else
 union {float f;uint32_t u;} v={x};
 uint32_t ax=v.u&0x7fffffffU,sign=v.u>>31;
 if(sign||ax<0x3f800000U||ax>0x7f800000U)return 0U;
 if(ax>=0x437f0000U)return 255U;
 return (uint8_t)(((ax&0x7fffffU)|0x800000U)>>(150U-(ax>>23)));
#endif
}
static inline float t3p_min(float x,float y) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=x;TINY3TPU_FPU_REG_F32(0x04U)=y;
 return TINY3TPU_FPU_REG_F32(0x30U);
#else
 union {float f;uint32_t u;} a={x},b={y};
 if((a.u&0x7fffffffU)>0x7f800000U)return x;
 if((b.u&0x7fffffffU)>0x7f800000U)return y;
 int32_t ka=(int32_t)(a.u^((uint32_t)((int32_t)a.u>>31)&0x7fffffffU));
 int32_t kb=(int32_t)(b.u^((uint32_t)((int32_t)b.u>>31)&0x7fffffffU));
 return ka<kb?x:y;
#endif
}
static inline float t3p_max(float x,float y) {
#if TINY3TPU_FPU_MMIO
 TINY3TPU_FPU_REG_F32(0x00U)=x;TINY3TPU_FPU_REG_F32(0x04U)=y;
 return TINY3TPU_FPU_REG_F32(0x34U);
#else
 union {float f;uint32_t u;} a={x},b={y};
 if((a.u&0x7fffffffU)>0x7f800000U)return x;
 if((b.u&0x7fffffffU)>0x7f800000U)return y;
 int32_t ka=(int32_t)(a.u^((uint32_t)((int32_t)a.u>>31)&0x7fffffffU));
 int32_t kb=(int32_t)(b.u^((uint32_t)((int32_t)b.u>>31)&0x7fffffffU));
 return ka>kb?x:y;
#endif
}
static inline float t3p_div(float a,float b) {
 union {float f;uint32_t u;} va={a},vb={b};
 uint32_t ua=va.u,ub=vb.u,sign=(ua^ub)&0x80000000U;
 uint32_t exp_a=(ua>>23)&0xffU,exp_b=(ub>>23)&0xffU;
 if(exp_a==0U||exp_a==0xffU||exp_b==0U||exp_b==0xffU)return a/b;
 uint32_t ma=(ua&0x7fffffU)|0x800000U,mb=(ub&0x7fffffU)|0x800000U;
 int exp=(int)exp_a-(int)exp_b+127;
 if(mb==0x800000U){
  if(exp>0&&exp<0xff){va.u=sign|((uint32_t)exp<<23)|(ua&0x7fffffU);return va.f;}
  return a/b;
 }
 uint32_t q0=ma>=mb,r=q0?(ma-mb):ma;
 if(!q0)--exp;
 if(exp<=0||exp>=0xff)return a/b;
 uint32_t n1=r<<8,q1=n1/mb,r1=n1-q1*mb;
 uint32_t n2=r1<<8,q2=n2/mb,r2=n2-q2*mb;
 uint32_t n3=r2<<8,q3=n3/mb,r3=n3-q3*mb;
 uint32_t q=(q0<<24)|(q1<<16)|(q2<<8)|q3,mant;
 if(q0){
  uint32_t round_bit=q&1U;mant=q>>1;
  mant+=round_bit&((r3!=0U)|(mant&1U));
 }else{
  mant=q;uint32_t twice_r=r3<<1;
  mant+=(twice_r>mb)|((twice_r==mb)&(mant&1U));
 }
 if(mant>=0x1000000U){mant>>=1;if(++exp>=0xff)return a/b;}
 va.u=sign|((uint32_t)exp<<23)|(mant&0x7fffffU);
 return va.f;
}
#endif
