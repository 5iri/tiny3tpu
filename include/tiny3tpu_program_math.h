#ifndef TINY3TPU_PROGRAM_MATH_H
#define TINY3TPU_PROGRAM_MATH_H
#include <stdint.h>
static inline float t3p_f32(uint32_t x) {union {uint32_t u;float f;} v={x};return v.f;}
/* Freestanding float32 CPU fallback; no host runtime or allocation. */
static inline int t3p_finite(float x) { union {float f; uint32_t u;} v={x};return (v.u&0x7f800000U)!=0x7f800000U; }
static inline float t3p_sqrt(float x) {
 if(x==0)return x;
 if(!t3p_finite(x))return x>0?x:x-x;
 if(x<0){union {uint32_t u;float f;} v={0x7fc00000U};return v.f;}
 int subnormal=x<0x1p-126f;if(subnormal)x*=0x1p24f;
 union {float f;uint32_t u;} v={x};v.u=(v.u>>1)+0x1fc00000U;
 float r=v.f;for(unsigned i=0;i<5;i++)r=.5f*(r+x/r);return subnormal?r*0x1p-12f:r;
}
/* Explicit freestanding exponential approximation. Reduce to +/- ln(2)/2,
 * evaluate a degree-7 Taylor polynomial, then scale by a power of two.
 * Split ln(2) reduces cancellation; subnormal scaling avoids bit tricks on
 * negative exponents. NaN/infinities and overflow/underflow are handled first. */
static inline float t3p_exp(float x) {
 if(x!=x)return x+x;
 if(x>0x1.62e42ep6f)return t3p_f32(0x7f800000U);
 if(x< -0x1.9fe368p6f)return 0.f;
 float scaled=x*0x1.715476p0f;
 int n=(int)(scaled+(scaled<0?-.5f:.5f));
 float r=(x-(float)n*0x1.62e400p-1f)-(float)n*0x1.7f7d1cp-20f;
 float y=1.f+r*(1.f+r*(.5f+r*(1.f/6.f+r*(1.f/24.f+r*(1.f/120.f+r*(1.f/720.f+r/5040.f))))));
 if(n>127)return (y*2.f)*0x1p127f;
 if(n< -126)return (y*t3p_f32((uint32_t)(n+24+127)<<23))*0x1p-24f;
 return y*t3p_f32((uint32_t)(n+127)<<23);
}
static inline float t3p_atan(float x) {
 int inv=x>1.f;if(inv)x=1.f/x;
 int rotate=x>.414213562373095f;if(rotate)x=(x-1.f)/(x+1.f);
 float xx=x*x,sum=1.f/19.f;
 for(int k=17;k>=1;k-=2)sum=1.f/(float)k-xx*sum;
 float r=x*sum;if(rotate)r+=.7853981633974483f;
 return inv?1.5707963267948966f-r:r;
}
static inline float t3p_acos(float x) {
 if(x==1.f)return 0.f;
 if(x== -1.f)return 3.141592653589793f;
 if(x< -1.f||x>1.f)return t3p_sqrt(-1.f);
 float a=x<0?-x:x;float r=2.f*t3p_atan(t3p_sqrt((1.f-a)/(1.f+a)));
 return x<0?3.141592653589793f-r:r;
}
static inline float t3p_atan2(float y,float x) {
 union {float f;uint32_t u;} a={x},b={y};
 uint32_t ax=a.u&0x7fffffffU,ay=b.u&0x7fffffffU;
 int sx=(int)(a.u>>31),sy=(int)(b.u>>31);
 float r;
 if(ax>0x7f800000U||ay>0x7f800000U)return x+y;
 if(ay==0)return sx?(sy?-3.141592653589793f:3.141592653589793f):y;
 if(ax==0||ay==0x7f800000U) {
  r=ax==0x7f800000U?.7853981633974483f:1.5707963267948966f;
 } else if(ax==0x7f800000U)r=0.f;
 else {a.u=ax;b.u=ay;r=t3p_atan(b.f/a.f);}
 if(sx)r=3.141592653589793f-r;
 return sy?-r:r;
}
/* Full binary32-domain argument reduction. 2/pi is stored as a 256-bit
 * fixed-point integer; its truncation contributes <2^-128 turns even at
 * FLT_MAX. No float-to-integer conversion of a huge angle is performed.
 * Double arithmetic is used only for the reduced fraction (libgcc on RV32). */
static inline uint32_t t3p_bit(const uint32_t *words,unsigned bit) {
 return (words[bit/32]>>(bit%32))&1U;
}
static inline float t3p_sincos(float x,int cosine) {
 static const uint32_t two_over_pi[8]={0xdebbc561U,0xfe5163abU,0x3c439041U,0xdb629599U,
                                      0xf534ddc0U,0xfc2757d1U,0x4e441529U,0xa2f9836eU};
 union {float f;uint32_t u;} v={x};uint32_t ax=v.u&0x7fffffffU;unsigned sign=v.u>>31;
 if(ax>=0x7f800000U)return x-x;
 unsigned quadrant=0;float r;
 if(ax<=0x3f490fdbU){v.u=ax;r=v.f;}
 else {
  unsigned exponent=ax>>23,shift=406-exponent;
  uint32_t mantissa=(ax&0x7fffffU)|0x800000U,product[9];uint64_t carry=0;
  for(unsigned i=0;i<8;i++){uint64_t part=(uint64_t)two_over_pi[i]*mantissa+carry;product[i]=(uint32_t)part;carry=part>>32;}
  product[8]=(uint32_t)carry;
  quadrant=t3p_bit(product,shift)|(t3p_bit(product,shift+1)<<1);
  uint64_t fraction=0;
  for(unsigned i=0;i<64;i++)fraction=(fraction<<1)|t3p_bit(product,shift-1-i);
  double f=(double)(uint32_t)(fraction>>32)*0x1p-32+(double)(uint32_t)fraction*0x1p-64;
  if(fraction>>63){quadrant=(quadrant+1)&3U;f-=1.;}
  r=(float)(f*0x1.921fb54442d18p+0);
 }
 float z=r*r;
 float s=r+r*z*(-1.f/6.f+z*(1.f/120.f+z*(-1.f/5040.f+z*(1.f/362880.f+z*(-1.f/39916800.f+z/6227020800.f)))));
 float c=1.f+z*(-.5f+z*(1.f/24.f+z*(-1.f/720.f+z*(1.f/40320.f+z*(-1.f/3628800.f+z/479001600.f)))));
 if(cosine)quadrant=(quadrant+1)&3U;
 float result=quadrant==0?s:quadrant==1?c:quadrant==2?-s:-c;
 return !cosine&&sign?-result:result;
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
/* Saturating float-to-integer conversion; NaN maps to zero. */
static inline int32_t t3p_to_int32(float x) {
 if(x!=x)return 0;
 if(x>=0x1p31f)return INT32_MAX;
 if(x<=-0x1p31f)return INT32_MIN;
 return (int32_t)x;
}
static inline uint32_t t3p_to_uint32(float x) {
 if(!(x>0))return 0;
 if(x>=0x1p32f)return UINT32_MAX;
 return (uint32_t)x;
}
static inline int8_t t3p_to_int8(float x) {
 if(x!=x)return 0;
 return x>=127?127:x<=-128?-128:(int8_t)x;
}
static inline uint8_t t3p_to_uint8(float x) {
 if(!(x>0))return 0;
 return x>=255?255:(uint8_t)x;
}
static inline float t3p_min(float x,float y) {
 if(x!=x)return x;
 if(y!=y)return y;
 if(x==0&&y==0){union {float f;uint32_t u;} a={x},b={y};a.u|=b.u;return a.f;}
 return x<y?x:y;
}
static inline float t3p_max(float x,float y) {
 if(x!=x)return x;
 if(y!=y)return y;
 if(x==0&&y==0){union {float f;uint32_t u;} a={x},b={y};a.u&=b.u;return a.f;}
 return x>y?x:y;
}
#endif
