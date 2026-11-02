/* Native fake-MMIO test of the production UDP application adapter. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static uint32_t fake_read32(uint32_t address);
static void fake_write32(uint32_t address,uint32_t value);
#define TINY3TPU_ETHERNET 1
#define TINY3TPU_DEMO_READ32(address) fake_read32(address)
#define TINY3TPU_DEMO_WRITE32(address,value) fake_write32(address,value)
#include "tiny3tpu_demo_transport.h"

static uint32_t rx_words[384],tx_words[384],rx_length,rx_ip,rx_ports,tx_length,tx_ip,tx_ports;
static unsigned rx_valid,tx_wait,releases,sent_count,status_reads;
static uint32_t version=0x00010000U;
static struct packet {uint32_t length,ip,ports;uint8_t data[1472];} sent[128];

static uint32_t word(const uint8_t *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static void store(uint8_t *p,uint32_t value) {
    for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(value>>(i*8));
}
static uint32_t fake_read32(uint32_t address) {
    assert(address>=TINY3TPU_DEMO_NET_BASE);unsigned offset=address-TINY3TPU_DEMO_NET_BASE;
    switch(offset){
    case 0:status_reads++;if(tx_wait)tx_wait--;return rx_valid|(tx_wait?0U:2U);
    case 4:return rx_length;
    case 8:return rx_ip;
    case 12:return rx_ports;
    case 40:return version;
    default:
        assert(rx_valid&&offset>=0x400U&&offset<0xa00U&&!(offset&3U));
        return rx_words[(offset-0x400U)/4U];
    }
}
static void fake_write32(uint32_t address,uint32_t value) {
    assert(address>=TINY3TPU_DEMO_NET_BASE);unsigned offset=address-TINY3TPU_DEMO_NET_BASE;
    if(offset==28U){
        if(value&1U){assert(rx_valid);rx_valid=0;releases++;}
        if(value&2U){
            assert(!tx_wait&&tx_length>=20U&&tx_length<=1472U&&sent_count<128U);
            struct packet *packet=&sent[sent_count++];
            packet->length=tx_length;packet->ip=tx_ip;packet->ports=tx_ports;
            for(unsigned i=0;i<tx_length;i++)packet->data[i]=(uint8_t)(tx_words[i/4]>>(8*(i%4)));
            tx_wait=4; /* Exercise transmitter backpressure between fragments. */
        }
        return;
    }
    assert(!tx_wait);
    if(offset==16U)tx_length=value;
    else if(offset==20U)tx_ip=value;
    else if(offset==24U)tx_ports=value;
    else {assert(offset>=0x1000U&&offset<0x1600U&&!(offset&3U));tx_words[(offset-0x1000U)/4U]=value;}
}
static void inject(uint32_t ip,uint32_t ports,uint32_t transaction,const uint8_t *data,unsigned length) {
    assert(!rx_valid&&length<=1400U);
    uint8_t bytes[1420];memset(bytes,0xa6,sizeof(bytes));
    store(bytes,0x31553354U);store(bytes+4,transaction);store(bytes+8,length);store(bytes+12,0);store(bytes+16,length);
    memcpy(bytes+20,data,length);
    for(unsigned i=0;i<(length+23U)/4U;i++)rx_words[i]=word(bytes+i*4U);
    rx_length=length+20U;rx_ip=ip;rx_ports=ports;rx_valid=1;
}
static void check_reply(unsigned first,uint32_t id,const uint8_t *data,unsigned length,uint32_t ip,uint32_t ports) {
    unsigned fragments=length?(length+1399U)/1400U:1U;assert(sent_count==first+fragments);
    unsigned offset=0;
    for(unsigned i=first;i<sent_count;i++){
        const struct packet *packet=&sent[i];unsigned count=length-offset;if(count>1400U)count=1400U;
        assert(packet->ip==ip&&packet->ports==((ports<<16)|(ports>>16)));
        assert(packet->length==20U+count&&word(packet->data)==0x31553354U);
        assert(word(packet->data+4)==id&&word(packet->data+8)==length);
        assert(word(packet->data+12)==offset&&word(packet->data+16)==count);
        assert(!memcmp(packet->data+20,data+offset,count));offset+=count;
    }
}
static void check_error(unsigned first,uint32_t id,unsigned code,unsigned detail,uint32_t ip,uint32_t ports) {
    uint8_t data[12];store(data,0x31524545U);store(data+4,code);store(data+8,detail);
    check_reply(first,id,data,sizeof(data),ip,ports);
}
static void check_hello(unsigned ownership,uint32_t last,unsigned valid,uint32_t ip,uint32_t ports) {
    unsigned first=sent_count;const uint8_t request[]={'E','H','Q','1'};
    uint8_t response[20];store(response,0x31524845U);store(response+4,1);store(response+8,ownership);
    store(response+12,last);store(response+16,valid);
    inject(ip,ports,0x12345678U,request,sizeof(request));assert(!tiny3tpu_demo_poll(0x31514649U,16));
    check_reply(first,0x12345678U,response,sizeof(response),ip,ports);
}
static void consume(const uint8_t *request,unsigned length) {
    for(unsigned i=0;i<length;i++)assert(tiny3tpu_demo_get_byte()==request[i]);
    assert(tiny3tpu_demo_get_byte()==0U);
}
int main(void) {
    const uint32_t ip=0xc0a80164U,ports=(9000U<<16)|9002U,other=0xc0a80165U;
    uint8_t request[16]={'I','F','Q','1',1,0,0,0,3,0,0,0,1,0,0,0};
    assert(!tiny3tpu_demo_init());version=2;assert(tiny3tpu_demo_init()==-1);version=0x10000U;
    check_hello(0,0,0,ip,ports);
    /* Echo preserves every byte, including a partial final word, and is read-only. */
    uint8_t echo[1377];for(unsigned i=0;i<sizeof(echo);i++)echo[i]=(uint8_t)(i*37U);
    memcpy(echo,"ECQ1",4);unsigned first=sent_count;
    inject(ip,ports,55,echo,sizeof(echo));assert(!tiny3tpu_demo_poll(0x31514649U,16));
    echo[2]='R';check_reply(first,55,echo,sizeof(echo),ip,ports);check_hello(0,0,0,other,ports);

    inject(ip,ports,0xfffffffeU,request,sizeof(request));assert(tiny3tpu_demo_poll(0x31514649U,16));consume(request,sizeof(request));
    /* Mix aligned/unaligned word writes and byte writes through the real API. */
    uint8_t response[4096];unsigned cursor=0;
    while(cursor<sizeof(response)){
        if(cursor%7U && sizeof(response)-cursor>=4U){
            uint32_t value=0x78563412U^cursor;store(response+cursor,value);tiny3tpu_demo_put_word(value);cursor+=4;
        }else {response[cursor]=(uint8_t)(cursor*17U);tiny3tpu_demo_put_byte(response[cursor]);cursor++;}
    }
    first=sent_count;tiny3tpu_demo_end();check_reply(first,0xfffffffeU,response,sizeof(response),ip,ports);
    check_hello(1,0xfffffffeU,1,ip,ports);check_hello(2,0xfffffffeU,1,other,ports);

    /* A hello or echo must not overwrite the cached application reply. */
    echo[2]='Q';first=sent_count;inject(other,ports,99,echo,sizeof(echo));assert(!tiny3tpu_demo_poll(0x31514649U,16));
    echo[2]='R';check_reply(first,99,echo,sizeof(echo),other,ports);
    first=sent_count;inject(ip,ports,0xfffffffeU,request,sizeof(request));assert(!tiny3tpu_demo_poll(0x31514649U,16));
    check_reply(first,0xfffffffeU,response,sizeof(response),ip,ports);

    first=sent_count;inject(other,ports,7,request,sizeof(request));assert(!tiny3tpu_demo_poll(0x31514649U,16));
    check_error(first,7,1,0,other,ports);
    first=sent_count;request[4]^=1;inject(ip,ports,0xfffffffeU,request,sizeof(request));assert(!tiny3tpu_demo_poll(0x31514649U,16));
    check_error(first,0xfffffffeU,3,0xfffffffeU,ip,ports);request[4]^=1;
    const uint32_t stale[]={0xfffffffdU,0x7ffffffeU};
    for(unsigned i=0;i<2;i++){
        first=sent_count;inject(ip,ports,stale[i],request,sizeof(request));assert(!tiny3tpu_demo_poll(0x31514649U,16));
        check_error(first,stale[i],2,0xfffffffeU,ip,ports);
    }
    /* Advancing through 0xffffffff to zero is valid; delayed older IDs are not. */
    for(unsigned i=0;i<2;i++){
        uint32_t id=i?0U:0xffffffffU;inject(ip,ports,id,request,sizeof(request));assert(tiny3tpu_demo_poll(0x31514649U,16));
        consume(request,sizeof(request));tiny3tpu_demo_put_word(0x31524649U);first=sent_count;tiny3tpu_demo_end();
        check_reply(first,id,(const uint8_t *)"IFR1",4,ip,ports);
    }
    first=sent_count;inject(ip,ports,0xfffffffeU,request,sizeof(request));assert(!tiny3tpu_demo_poll(0x31514649U,16));
    check_error(first,0xfffffffeU,2,0,ip,ports);

    /* Malformed metadata, fragmented requests, and wrong application lengths
     * are dropped before parsing or changing the transaction high water mark. */
    for(unsigned fault=0;fault<8;fault++){
        first=sent_count;inject(ip,ports,1,request,sizeof(request));
        switch(fault){case 0:rx_length=19;break;case 1:rx_length=1421;break;case 2:rx_words[0]^=1;break;
        case 3:rx_words[2]++;break;case 4:rx_words[3]=1;break;case 5:rx_words[4]--;break;
        case 6:rx_words[5]^=1;break;case 7:rx_length-=4;rx_words[2]-=4;rx_words[4]-=4;break;}
        assert(!tiny3tpu_demo_poll(0x31514649U,16));assert(sent_count==first&&!rx_valid);
        assert(tiny3tpu_demo_net.transaction==0);
    }
    /* An oversized generated response is never sent as a truncated success,
     * and retrying it cannot run the stateful request a second time. */
    inject(ip,ports,1,request,sizeof(request));assert(tiny3tpu_demo_poll(0x31514649U,16));consume(request,sizeof(request));
    for(unsigned i=0;i<4097;i++)tiny3tpu_demo_put_byte(i);
    first=sent_count;tiny3tpu_demo_end();assert(sent_count==first);
    inject(ip,ports,1,request,sizeof(request));assert(!tiny3tpu_demo_poll(0x31514649U,16));assert(sent_count==first);
    check_hello(1,1,1,ip,ports);
    assert(releases>20&&status_reads>sent_count);
    puts("PASS UDP adapter: peer metadata, hello, echo, fragmentation, word/byte writes, backpressure, duplicate replay, stale/conflicting IDs, wrap, bounds");
    return 0;
}
