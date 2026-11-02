#ifndef TINY3TPU_DEMO_TRANSPORT_H
#define TINY3TPU_DEMO_TRANSPORT_H
#include <stdint.h>

/* Application byte protocols stay unchanged. Ethernet builds put each request
 * in one UDP packet and fragment replies at the application layer; UART builds
 * preserve the original stream, including the startup banner. */
#ifndef TINY3TPU_ETHERNET
#define TINY3TPU_ETHERNET 0
#endif
#ifndef TINY3TPU_CLOCK_HZ
#define TINY3TPU_CLOCK_HZ 100000000U
#endif
#ifndef TINY3TPU_DEMO_READ32
static inline uint32_t tiny3tpu_demo_mmio_read(uint32_t address) {
#if TINY3TPU_ETHERNET
    __asm__ volatile("fence iorw, iorw" ::: "memory");
#endif
    uint32_t value=*(volatile uint32_t *)(uintptr_t)address;
#if TINY3TPU_ETHERNET
    __asm__ volatile("fence iorw, iorw" ::: "memory");
#endif
    return value;
}
#define TINY3TPU_DEMO_READ32(address) tiny3tpu_demo_mmio_read(address)
#endif
#ifndef TINY3TPU_DEMO_WRITE32
static inline void tiny3tpu_demo_mmio_write(uint32_t address,uint32_t value) {
#if TINY3TPU_ETHERNET
    __asm__ volatile("fence iorw, iorw" ::: "memory");
#endif
    *(volatile uint32_t *)(uintptr_t)address=value;
#if TINY3TPU_ETHERNET
    __asm__ volatile("fence iorw, iorw" ::: "memory");
#endif
}
#define TINY3TPU_DEMO_WRITE32(address,value) tiny3tpu_demo_mmio_write(address,value)
#endif

#if TINY3TPU_ETHERNET
#ifndef TINY3TPU_MAX_REQUEST_BYTES
#define TINY3TPU_MAX_REQUEST_BYTES 16U
#endif
#ifndef TINY3TPU_MAX_RESPONSE_BYTES
#define TINY3TPU_MAX_RESPONSE_BYTES 4096U
#endif
_Static_assert(TINY3TPU_MAX_REQUEST_BYTES>=4U && TINY3TPU_MAX_REQUEST_BYTES<=1400U,
               "request cache must fit one UDP application fragment");
_Static_assert(TINY3TPU_MAX_RESPONSE_BYTES>0U && TINY3TPU_MAX_RESPONSE_BYTES<=4096U,
               "reply cache exceeds protocol limit");
enum {
    TINY3TPU_DEMO_NET_BASE=0x20004000U,
    TINY3TPU_DEMO_NET_STATUS=0x00U,
    TINY3TPU_DEMO_NET_RX_LEN=0x04U,
    TINY3TPU_DEMO_NET_RX_IP=0x08U,
    TINY3TPU_DEMO_NET_RX_PORTS=0x0cU,
    TINY3TPU_DEMO_NET_TX_LEN=0x10U,
    TINY3TPU_DEMO_NET_TX_IP=0x14U,
    TINY3TPU_DEMO_NET_TX_PORTS=0x18U,
    TINY3TPU_DEMO_NET_COMMAND=0x1cU,
    TINY3TPU_DEMO_NET_VERSION=0x28U,
    TINY3TPU_DEMO_NET_RX_DATA=0x400U,
    TINY3TPU_DEMO_NET_TX_DATA=0x1000U,
    TINY3TPU_DEMO_UDP_HEADER=20U,
    TINY3TPU_DEMO_UDP_CHUNK=1400U,
    TINY3TPU_DEMO_REPLY_MAX=TINY3TPU_MAX_RESPONSE_BYTES
};
static struct {
    uint8_t request[TINY3TPU_MAX_REQUEST_BYTES];
    union {
        uint32_t words[(TINY3TPU_DEMO_REPLY_MAX+3U)/4U];
        uint8_t bytes[TINY3TPU_DEMO_REPLY_MAX];
    } reply;
    uint32_t request_length,request_cursor,reply_length;
    uint32_t peer_ip,peer_ports,transaction;
    unsigned peer_valid,reply_valid,reply_overflow;
} tiny3tpu_demo_net;

static inline uint32_t tiny3tpu_demo_net_read(unsigned offset) {
    return TINY3TPU_DEMO_READ32(TINY3TPU_DEMO_NET_BASE+offset);
}
static inline void tiny3tpu_demo_net_write(unsigned offset,uint32_t value) {
    TINY3TPU_DEMO_WRITE32(TINY3TPU_DEMO_NET_BASE+offset,value);
}
static void tiny3tpu_demo_packet_begin(uint32_t ip,uint32_t ports,uint32_t transaction,
                                      uint32_t total,uint32_t offset,uint32_t count) {
    while(!(tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_STATUS)&2U)){}
    const uint32_t header[5]={UINT32_C(0x31553354),transaction,total,offset,count};
    for(unsigned i=0;i<5;i++)tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_TX_DATA+i*4U,header[i]);
    tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_TX_LEN,TINY3TPU_DEMO_UDP_HEADER+count);
    tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_TX_IP,ip);
    /* RX ports are source,destination; the response reverses them. */
    tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_TX_PORTS,(ports<<16)|(ports>>16));
}
static void tiny3tpu_demo_control(uint32_t ip,uint32_t ports,uint32_t transaction,
                                 const uint32_t *words,unsigned count) {
    tiny3tpu_demo_packet_begin(ip,ports,transaction,count*4U,0,count*4U);
    for(unsigned i=0;i<count;i++)
        tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_TX_DATA+TINY3TPU_DEMO_UDP_HEADER+i*4U,words[i]);
    tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,2U);
}
static void tiny3tpu_demo_error(uint32_t ip,uint32_t ports,uint32_t transaction,
                               uint32_t code,uint32_t detail) {
    const uint32_t words[3]={UINT32_C(0x31524545),code,detail}; /* EER1 */
    tiny3tpu_demo_control(ip,ports,transaction,words,3);
}
static void tiny3tpu_demo_send_reply(void) {
    uint32_t offset=0;
    do {
        uint32_t count=tiny3tpu_demo_net.reply_length-offset;
        if(count>TINY3TPU_DEMO_UDP_CHUNK)count=TINY3TPU_DEMO_UDP_CHUNK;
        tiny3tpu_demo_packet_begin(tiny3tpu_demo_net.peer_ip,tiny3tpu_demo_net.peer_ports,
            tiny3tpu_demo_net.transaction,tiny3tpu_demo_net.reply_length,offset,count);
        /* The RV32 target is little-endian. Chunk boundaries are word-aligned;
         * UDP length excludes unused high bytes of the final payload word. */
        for(uint32_t i=0;i<count;i+=4U)
            tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_TX_DATA+TINY3TPU_DEMO_UDP_HEADER+i,
                                    tiny3tpu_demo_net.reply.words[(offset+i)/4U]);
        tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,2U);
        offset+=count;
    } while(offset<tiny3tpu_demo_net.reply_length);
}

/* Poll one complete datagram. Invalid packets never enter the byte parser.
 * The active peer owns this session until reset; transaction numbers advance
 * modulo 2^32 with a maximum forward distance of 2^31-1. Cache the last reply
 * so duplicate UDP delivery cannot advance stateful applications twice. */
static int tiny3tpu_demo_poll(uint32_t request_magic,uint32_t request_length) {
    if(!(tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_STATUS)&1U))return 0;
    uint32_t length=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_LEN);
    uint32_t ip=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_IP);
    uint32_t ports=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_PORTS);
    if(length<TINY3TPU_DEMO_UDP_HEADER || length>TINY3TPU_DEMO_UDP_HEADER+TINY3TPU_DEMO_UDP_CHUNK)goto discard;
    uint32_t magic=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA);
    uint32_t transaction=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA+4U);
    uint32_t total=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA+8U);
    uint32_t offset=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA+12U);
    uint32_t count=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA+16U);
    if(magic!=UINT32_C(0x31553354)||offset||count!=total||count!=length-TINY3TPU_DEMO_UDP_HEADER||count<4U)goto discard;
    uint32_t inner=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA+TINY3TPU_DEMO_UDP_HEADER);
    if(inner==UINT32_C(0x31514845)&&count==4U){ /* EHQ1: read-only ownership query. */
        uint32_t ownership=!tiny3tpu_demo_net.peer_valid?0U:
            ip==tiny3tpu_demo_net.peer_ip&&ports==tiny3tpu_demo_net.peer_ports?1U:2U;
        const uint32_t hello[5]={UINT32_C(0x31524845),1U,ownership,
            tiny3tpu_demo_net.peer_valid?tiny3tpu_demo_net.transaction:0U,tiny3tpu_demo_net.peer_valid?1U:0U};
        tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,1U);
        tiny3tpu_demo_control(ip,ports,transaction,hello,5);return 0;
    }
    if(inner==UINT32_C(0x31514345)){ /* ECQ1: echo is read-only and never claims the board. */
        tiny3tpu_demo_packet_begin(ip,ports,transaction,count,0,count);
        for(uint32_t i=0;i<count;i+=4U){
            uint32_t word=i?tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA+TINY3TPU_DEMO_UDP_HEADER+i):UINT32_C(0x31524345);
            tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_TX_DATA+TINY3TPU_DEMO_UDP_HEADER+i,word);
        }
        tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,1U);
        tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,2U);return 0;
    }
    if(inner!=request_magic||count!=request_length||count>TINY3TPU_MAX_REQUEST_BYTES)goto discard;
    if(tiny3tpu_demo_net.peer_valid){
        if(ip!=tiny3tpu_demo_net.peer_ip||ports!=tiny3tpu_demo_net.peer_ports){
            tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,1U);
            tiny3tpu_demo_error(ip,ports,transaction,1U,0U);return 0;
        }
        uint32_t distance=transaction-tiny3tpu_demo_net.transaction;
        if(!distance){
            unsigned same=count==tiny3tpu_demo_net.request_length;
            for(uint32_t i=0;i<count&&same;i+=4U){
                uint32_t word=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA+TINY3TPU_DEMO_UDP_HEADER+i);
                for(unsigned lane=0;lane<4U&&i+lane<count;lane++)
                    if(((word>>(8U*lane))&255U)!=tiny3tpu_demo_net.request[i+lane])same=0;
            }
            tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,1U);
            if(!same){tiny3tpu_demo_error(ip,ports,transaction,3U,tiny3tpu_demo_net.transaction);return 0;}
            if(tiny3tpu_demo_net.reply_valid)tiny3tpu_demo_send_reply();
            return 0;
        }
        if(distance>=UINT32_C(0x80000000)){
            tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,1U);
            tiny3tpu_demo_error(ip,ports,transaction,2U,tiny3tpu_demo_net.transaction);return 0;
        }
    }
    for(uint32_t i=0;i<count;i+=4U){
        uint32_t word=tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_RX_DATA+TINY3TPU_DEMO_UDP_HEADER+i);
        for(unsigned lane=0;lane<4U&&i+lane<count;lane++)tiny3tpu_demo_net.request[i+lane]=(uint8_t)(word>>(8U*lane));
    }
    tiny3tpu_demo_net.peer_ip=ip;tiny3tpu_demo_net.peer_ports=ports;
    tiny3tpu_demo_net.transaction=transaction;tiny3tpu_demo_net.peer_valid=1;
    tiny3tpu_demo_net.request_length=count;tiny3tpu_demo_net.request_cursor=0;
    tiny3tpu_demo_net.reply_length=0;tiny3tpu_demo_net.reply_valid=0;tiny3tpu_demo_net.reply_overflow=0;
    tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,1U);
    return 1;
discard:
    tiny3tpu_demo_net_write(TINY3TPU_DEMO_NET_COMMAND,1U);return 0;
}
static inline int tiny3tpu_demo_init(void) {
    tiny3tpu_demo_net.peer_valid=0;tiny3tpu_demo_net.reply_valid=0;
    return tiny3tpu_demo_net_read(TINY3TPU_DEMO_NET_VERSION)==UINT32_C(0x00010000)?0:-1;
}
static inline void tiny3tpu_demo_begin(uint32_t magic,uint32_t length) {
    while(!tiny3tpu_demo_poll(magic,length)){}
}
static inline unsigned tiny3tpu_demo_get_byte(void) {
    return tiny3tpu_demo_net.request_cursor<tiny3tpu_demo_net.request_length ?
        tiny3tpu_demo_net.request[tiny3tpu_demo_net.request_cursor++] : 0U;
}
static inline void tiny3tpu_demo_put_byte(unsigned value) {
    if(tiny3tpu_demo_net.reply_length<TINY3TPU_DEMO_REPLY_MAX)
        tiny3tpu_demo_net.reply.bytes[tiny3tpu_demo_net.reply_length++]=(uint8_t)value;
    else tiny3tpu_demo_net.reply_overflow=1;
}
static inline void tiny3tpu_demo_put_word(uint32_t value) {
    const uint32_t offset=tiny3tpu_demo_net.reply_length;
    if(!(offset&3U)&&offset<=TINY3TPU_DEMO_REPLY_MAX&&TINY3TPU_DEMO_REPLY_MAX-offset>=4U){
        tiny3tpu_demo_net.reply.words[offset/4U]=value;tiny3tpu_demo_net.reply_length+=4U;
    } else for(unsigned i=0;i<4;i++)tiny3tpu_demo_put_byte(value>>(8U*i));
}
static inline void tiny3tpu_demo_end(void) {
    if(tiny3tpu_demo_net.reply_overflow||tiny3tpu_demo_net.request_cursor!=tiny3tpu_demo_net.request_length)return;
    tiny3tpu_demo_net.reply_valid=1;tiny3tpu_demo_send_reply();
}
static inline void tiny3tpu_demo_banner(const char *text) {(void)text;}
#else
static inline int tiny3tpu_demo_init(void) {
    const uint32_t divisor=(TINY3TPU_CLOCK_HZ+460800U)/921600U-1U;
    TINY3TPU_DEMO_WRITE32(0x2000000cU,0x83U);
    TINY3TPU_DEMO_WRITE32(0x20000000U,divisor&255U);
    TINY3TPU_DEMO_WRITE32(0x20000004U,divisor>>8);
    TINY3TPU_DEMO_WRITE32(0x2000000cU,3U);
    TINY3TPU_DEMO_WRITE32(0x20000008U,7U);return 0;
}
static inline void tiny3tpu_demo_begin(uint32_t magic,uint32_t length) {(void)magic;(void)length;}
static inline unsigned tiny3tpu_demo_get_byte(void) {
    while(!(TINY3TPU_DEMO_READ32(0x20000014U)&1U)){}
    return TINY3TPU_DEMO_READ32(0x20000000U)&255U;
}
static inline void tiny3tpu_demo_put_byte(unsigned value) {
    while(!(TINY3TPU_DEMO_READ32(0x20000014U)&32U)){}
    TINY3TPU_DEMO_WRITE32(0x20000000U,value&255U);
}
static inline void tiny3tpu_demo_put_word(uint32_t value) {
    for(unsigned i=0;i<4;i++)tiny3tpu_demo_put_byte(value>>(8U*i));
}
static inline void tiny3tpu_demo_end(void) {}
static inline void tiny3tpu_demo_banner(const char *text) {
    while(*text)tiny3tpu_demo_put_byte((unsigned char)*text++);
}
#endif
#endif
