/* Keep the default byte stream and clock-derived UART divisor unchanged. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
static uint32_t values[16],addresses[16],writes;
static uint32_t fake_read(uint32_t address) {assert(address==0x20000014U||address==0x20000000U);return address==0x20000014U?33U:0x1abU;}
static void fake_write(uint32_t address,uint32_t value) {assert(writes<16);addresses[writes]=address;values[writes++]=value;}
#define TINY3TPU_DEMO_READ32(address) fake_read(address)
#define TINY3TPU_DEMO_WRITE32(address,value) fake_write(address,value)
#include "tiny3tpu_demo_transport.h"
int main(void) {
    assert(!tiny3tpu_demo_init());assert(writes==5&&addresses[0]==0x2000000cU&&values[0]==0x83U);
    assert(values[1]==108U&&values[2]==0U&&values[3]==3U&&values[4]==7U);
    tiny3tpu_demo_begin(0x1234U,16);assert(tiny3tpu_demo_get_byte()==0xabU);
    tiny3tpu_demo_banner("hi");tiny3tpu_demo_put_word(0x78563412U);tiny3tpu_demo_put_byte(0x1ffU);tiny3tpu_demo_end();
    assert(writes==12&&values[5]=='h'&&values[6]=='i');
    assert(values[7]==0x12U&&values[8]==0x34U&&values[9]==0x56U&&values[10]==0x78U&&values[11]==0xffU);
    puts("PASS UART adapter: default divisor, banner, bytes and little-endian words");return 0;
}
