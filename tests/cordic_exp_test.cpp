#include "Vtiny3tpu_cordic_exp.h"
#include <bit>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>
#include <algorithm>
int main(){
 Vtiny3tpu_cordic_exp d;unsigned cycles=0,max_latency=0;float max_relative=0;unsigned max_ulp=0;
 auto tick=[&](){d.clk=0;d.eval();d.clk=1;d.eval();cycles++;};
 d.rst=1;d.in_valid=0;d.out_ready=0;tick();d.rst=0;tick();
 std::vector<float> values={0.f,-0.f,INFINITY,-INFINITY,NAN,-104.f,-103.97208f,-103.f,-100.f,-87.3f,88.7f,88.72283f,88.72284f,89.f};
 std::mt19937 rng(705);std::uniform_real_distribution<float> range(-104.f,89.f);
 for(unsigned i=0;i<20000;i++)values.push_back(range(rng));
 for(unsigned i=0;i<20000;i++)values.push_back(std::bit_cast<float>(uint32_t(rng())));
 for(float input:values){
  unsigned start=cycles;if(!d.in_ready)return 1;
  d.in_bits=std::bit_cast<uint32_t>(input);d.in_valid=1;tick();d.in_valid=0;
  while(!d.out_valid){tick();if(cycles-start>256)return 2;}
  max_latency=std::max(max_latency,cycles-start);
  uint32_t bits=d.out_bits;float got=std::bit_cast<float>(bits),wanted=std::exp(input);
  if(std::isnan(wanted)){if(!std::isnan(got))return 3;}
  else if(std::isinf(wanted)){if(!std::isinf(got))return 4;}
  else {
   unsigned expected=std::bit_cast<uint32_t>(wanted),ulp=bits>expected?bits-expected:expected-bits;
   max_ulp=std::max(max_ulp,ulp);
   float relative=wanted>=0x1p-126f?std::abs(got-wanted)/wanted:0;max_relative=std::max(max_relative,relative);
   if(ulp>8||(wanted>=0x1p-126f&&relative>8e-7f)){
    std::cerr<<"FAIL x="<<input<<" actual="<<got<<" expected="<<wanted<<" ulp="<<ulp<<" rel="<<relative<<"\n";return 5;
   }
  }
  // Output holds for three cycles; input must remain blocked.
  for(int i=0;i<3;i++){tick();if(!d.out_valid||d.out_bits!=bits||d.in_ready)return 6;}
  d.out_ready=1;tick();d.out_ready=0;tick();
 }
 // Reset cancels work and allows a fresh request.
 d.in_bits=std::bit_cast<uint32_t>(1.f);d.in_valid=1;tick();d.in_valid=0;tick();d.rst=1;tick();d.rst=0;tick();if(d.out_valid||!d.in_ready)return 7;
 std::cout<<"PASS vectors="<<values.size()<<" max_latency="<<max_latency<<" max_ulp="<<max_ulp<<" max_relative="<<max_relative<<" backpressure/reset checked\n";
}
