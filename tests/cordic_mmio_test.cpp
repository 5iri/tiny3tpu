#include "Vtiny3tpu_cordic_mmio.h"
#include <bit>
#include <cstdint>
#include <cmath>
#include <iostream>
int main(){
 Vtiny3tpu_cordic_mmio d;auto tick=[&](){d.clk=0;d.eval();d.clk=1;d.eval();};
 auto read=[&](unsigned a){d.addr=a;d.wr=0;d.eval();return uint32_t(d.rdata);};
 auto write=[&](unsigned a,uint32_t v,unsigned strobe=15){d.addr=a;d.wdata=v;d.wstrb=strobe;d.wr=1;tick();d.wr=0;d.eval();};
 d.wr=0;d.rst=1;tick();d.rst=0;tick();if(read(12)!=0x45585031||read(0))return 1;
 write(4,std::bit_cast<uint32_t>(1.f));write(4,std::bit_cast<uint32_t>(9.f),1);
 if(read(4)!=std::bit_cast<uint32_t>(1.f))return 2;
 write(0,1);if(!(read(0)&1))return 3;
 write(4,std::bit_cast<uint32_t>(2.f));write(0,1);if(!(read(0)&4))return 4;
 for(unsigned i=0;!(read(0)&2);i++){if(i>100)return 5;tick();}
 if(std::abs(std::bit_cast<float>(read(8))-std::exp(1.f))>4e-7f)return 6;
 write(0,2);if(read(0))return 7;
 write(0,1);for(unsigned i=0;!(read(0)&2);i++){if(i>100)return 8;tick();}
 if(std::abs(std::bit_cast<float>(read(8))-std::exp(2.f))>1e-6f)return 9;
 write(0,2);write(0,1);d.rst=1;tick();d.rst=0;tick();if(read(0))return 10;
 std::cout<<"PASS identity, partial writes, rejected overlapping start, result, clear, reset\n";
}
