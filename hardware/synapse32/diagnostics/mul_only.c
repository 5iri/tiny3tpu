#include <stdint.h>
static volatile uint32_t *const uart=(volatile uint32_t *)0x20000000;
static void ch(unsigned c){while(!(uart[5]&32)){} uart[0]=c;}
static void hex(uint32_t x){for(int i=28;i>=0;i-=4)ch("0123456789abcdef"[(x>>i)&15]);ch(' ');}
int main(void){
 uart[3]=0x83;uart[0]=868&255;uart[1]=868>>8;uart[3]=3;uart[2]=7;
 ch('B');ch('E');ch('G');ch('I');ch('N');ch('\n');
 static const uint32_t av[] = {3,7,0x1234,0x80000000u,0xffffffffu};
 static const uint32_t bv[] = {10,11,0x5678,2,7};
 static const uint32_t expected[] = {30,77,0x06260060u,0x00000000u,0xfffffff9u};
 for(unsigned rep=0;rep<5;rep++) {
  uint32_t out; uint32_t a=av[rep],b=bv[rep];
  __asm__ volatile("mul %0,%1,%2":"=r"(out):"r"(a),"r"(b));
  ch('M');ch(' ');hex(a);hex(b);hex(out);hex(expected[rep]);ch('\n');
  for (volatile unsigned gap=0; gap<8; gap++) __asm__ volatile("nop");
 }
 return 0;
}
