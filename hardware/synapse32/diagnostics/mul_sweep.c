#include <stdint.h>
static volatile uint32_t *const uart=(volatile uint32_t *)0x20000000;
static void ch(unsigned c){while(!(uart[5]&32)){} uart[0]=c;}
static void hex(uint32_t x){for(int i=28;i>=0;i-=4)ch("0123456789abcdef"[(x>>i)&15]);ch(' ');}
int main(void){
 uart[3]=0x83;uart[0]=868&255;uart[1]=868>>8;uart[3]=3;uart[2]=7;
 static const uint32_t b[] = {1,2,4,8,16,32,0x101,0x202,0x5555,0xaaaa,10};
 ch('B');ch('E');ch('G');ch('I');ch('N');ch('\n');
 for(unsigned i=0;i<sizeof(b)/sizeof(b[0]);i++) {
  uint32_t out; uint32_t a=1;
  __asm__ volatile("mul %0,%1,%2":"=r"(out):"r"(a),"r"(b[i]));
  ch('S');ch(' ');hex(b[i]);hex(out);hex(b[i]);ch('\n');
  for (volatile unsigned gap=0; gap<16; gap++) __asm__ volatile("nop");
 }
 return 0;
}
