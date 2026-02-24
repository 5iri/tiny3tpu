// Systolic array RPC firmware using lwIP UDP over AXI Ethernet Lite.
#include "xparameters.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "lwip/init.h"
#include "lwip/udp.h"
#include "lwip/timeouts.h"
#include "lwip/pbuf.h"
#include "netif/xadapter.h"
#include "netif/xemacliteif.h"
#include <string.h>

#pragma GCC optimize ("Os")

#ifndef XPAR_AXI_ETHERNETLITE_0_BASEADDR
#error "AXI Ethernet Lite baseaddr missing (assign in Address Editor and regen BSP)."
#endif

#define ETH_BASEADDR   XPAR_AXI_ETHERNETLITE_0_BASEADDR
#define UDP_PORT       5000

#define LED_GPIO_BASE  0x40010000U
#define SYS_CTRL_BASE  0x00010000U
#define REG_CTRL       0x0
#define REG_STATUS     0x4
#define REG_STREAM_LEN 0x8
#define REG_FLUSH_LEN  0xC

#define BRAM_A_BASE    0x40000000U
#define BRAM_B_BASE    0xC0000000U
#define BRAM_C_BASE    0xC2000000U

#define OPC_PING       0x00
#define OPC_SET_LEN    0x01
#define OPC_LOAD_A     0x10
#define OPC_LOAD_B     0x11
#define OPC_RUN        0x20
#define OPC_READ_C     0x21
#define OPC_VERSION    0x30
#define STATUS_OK      0x00
#define STATUS_BADLEN  0xEE
#define STATUS_BADOP   0xEF

#define MAX_TILE_COUNT 32
#define ETH_MAX_FRAME  1520

static struct netif netif_data;
static struct udp_pcb *rpc_pcb;

static const u8 mac_addr[6] = {0x00, 0x0A, 0x35, 0x40, 0xE0, 0x00};
static const u8 ip_addr_bytes[4]  = {192, 168, 0, 50};

static u32 mat_a[16] = {0};
static u32 mat_b[16] = {0};
static u16 stream_len = 8;
static u16 flush_len = 10;
static u16 tile_count = 1;
static int tile_count_locked = 0; // locked when caller provides explicit tile_count

static u8 rx_buf[ETH_MAX_FRAME] __attribute__((aligned(4), section(".bufmem")));
static u8 tx_buf[ETH_MAX_FRAME] __attribute__((aligned(4), section(".bufmem")));

static inline void write_reg(u32 off, u32 val) { Xil_Out32(SYS_CTRL_BASE + off, val); }
static inline u32  read_reg(u32 off)          { return Xil_In32(SYS_CTRL_BASE + off); }

static void set_leds(u32 pattern) { Xil_Out32(LED_GPIO_BASE, pattern & 0xF); }

static void put_u32le(u32 v, u8 *out) {
    out[0] = (u8)(v & 0xFF);
    out[1] = (u8)((v >> 8) & 0xFF);
    out[2] = (u8)((v >> 16) & 0xFF);
    out[3] = (u8)((v >> 24) & 0xFF);
}

static u32 get_u32le(const u8 *in) {
    return ((u32)in[0]) |
           ((u32)in[1] << 8) |
           ((u32)in[2] << 16) |
           ((u32)in[3] << 24);
}

// Simple IPv4 checksum (used for ICMP replies; kept for parity with old flow if needed later).
// Pack a 4x4 matrix (row-major) into 8 time-step words for the systolic array.
static void pack_a_words(const u32 *mat, u32 *a_words) {
    for (int t = 0; t < 8; t++) {
        u32 w = 0;
        for (int lane = 0; lane < 4; lane++) {
            int col = t - lane;
            u8 v = (col >= 0 && col < 4) ? (u8)(mat[lane * 4 + col] & 0xFF) : 0;
            w |= ((u32)v) << (8 * lane);
        }
        a_words[t] = w;
    }
}

// Pack a 4x4 matrix (row-major) into 8 time-step words for the systolic array.
static void pack_b_words(const u32 *mat, u32 *b_words) {
    for (int t = 0; t < 8; t++) {
        u32 w = 0;
        for (int lane = 0; lane < 4; lane++) {
            int row = t - lane;
            u8 v = (row >= 0 && row < 4) ? (u8)(mat[row * 4 + lane] & 0xFF) : 0;
            w |= ((u32)v) << (8 * lane);
        }
        b_words[t] = w;
    }
}

static void send_udp_payload(const ip_addr_t *dst_ip, u16_t dst_port,
                             const u8 *payload, u16_t payload_len) {
    if (!rpc_pcb || payload_len > ETH_MAX_FRAME) return;
    struct pbuf *p = pbuf_alloc(PBUF_TRANSPORT, payload_len, PBUF_RAM);
    if (!p) return;
    memcpy(p->payload, payload, payload_len);
    udp_sendto(rpc_pcb, p, dst_ip, dst_port);
    pbuf_free(p);
}

static void handle_rpc(const ip_addr_t *peer_ip, u16_t peer_port,
                       const u8 *payload, u16_t len) {
    if (len < 2) return;
    u8 op  = payload[0];
    u8 plen = payload[1];
    if ((u16)(plen + 2) > len) {
        u8 st = STATUS_BADLEN;
        send_udp_payload(peer_ip, peer_port, &st, 1);
        return;
    }
    const u8 *body = payload + 2;

    switch (op) {
    case OPC_PING:
        if (plen != 0) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
        { u8 st = STATUS_OK; send_udp_payload(peer_ip, peer_port, &st, 1); }
        break;
    case OPC_SET_LEN:
        if (plen != 4 && plen != 6) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
        {
            stream_len = (u16)get_u32le(body);      // lower 16 bits
            flush_len  = (u16)(get_u32le(body) >> 16);
            if (plen == 6) {
                tile_count = ((u16)body[4]) | ((u16)body[5] << 8);
                if (tile_count == 0 || tile_count > MAX_TILE_COUNT) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
                tile_count_locked = 1;
            } else {
                tile_count = 1;
                tile_count_locked = 0;
            }
            u8 st = STATUS_OK;
            send_udp_payload(peer_ip, peer_port, &st, 1);
        }
        break;
    case OPC_LOAD_A:
        if (plen == 0 || (plen % 64) != 0 || (plen/64) > MAX_TILE_COUNT) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
        {
            if (stream_len < 8) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
            int words = plen / 4;
            u32 tile_mat[16];
            u32 packed[8];
            int tile_idx = 0;
            for (int off = 0; off < words; off += 16, tile_idx++) {
                for (int i = 0; i < 16; i++) {
                    tile_mat[i] = get_u32le(&body[(off + i) * 4]);
                    if (off == 0) mat_a[i] = tile_mat[i];
                }
                pack_a_words(tile_mat, packed);
                for (int t = 0; t < stream_len; t++) {
                    u32 v = (t < 8) ? packed[t] : 0;
                    Xil_Out32(BRAM_A_BASE + (tile_idx * stream_len + t)*4, v);
                }
            }
            int payload_tiles = plen / 64;
            if (payload_tiles > 0) {
                if (tile_count_locked) {
                    if (payload_tiles != tile_count) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
                } else {
                    tile_count = (u16)payload_tiles;
                }
            }
            Xil_DCacheFlushRange(BRAM_A_BASE, tile_count * stream_len * 4);
            u8 st = STATUS_OK;
            send_udp_payload(peer_ip, peer_port, &st, 1);
        }
        break;
    case OPC_LOAD_B:
        if (plen == 0 || (plen % 64) != 0 || (plen/64) > MAX_TILE_COUNT) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
        {
            if (stream_len < 8) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
            int words = plen / 4;
            u32 tile_mat[16];
            u32 packed[8];
            int tile_idx = 0;
            for (int off = 0; off < words; off += 16, tile_idx++) {
                for (int i = 0; i < 16; i++) {
                    tile_mat[i] = get_u32le(&body[(off + i) * 4]);
                    if (off == 0) mat_b[i] = tile_mat[i];
                }
                pack_b_words(tile_mat, packed);
                for (int t = 0; t < stream_len; t++) {
                    u32 v = (t < 8) ? packed[t] : 0;
                    Xil_Out32(BRAM_B_BASE + (tile_idx * stream_len + t)*4, v);
                }
            }
            int payload_tiles = plen / 64;
            if (payload_tiles > 0) {
                if (tile_count_locked) {
                    if (payload_tiles != tile_count) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
                } else {
                    tile_count = (u16)payload_tiles;
                }
            }
            Xil_DCacheFlushRange(BRAM_B_BASE, tile_count * stream_len * 4);
            u8 st = STATUS_OK;
            send_udp_payload(peer_ip, peer_port, &st, 1);
        }
        break;
    case OPC_RUN:
        if (plen != 0) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
        {
            if (tile_count == 1) {
                u32 a_words[8], b_words[8];
                pack_a_words(mat_a, a_words);
                pack_b_words(mat_b, b_words);
                for (int i = 0; i < 8; i++) {
                    Xil_Out32(BRAM_A_BASE + i*4, a_words[i]);
                    Xil_Out32(BRAM_B_BASE + i*4, b_words[i]);
                }
                Xil_DCacheFlushRange(BRAM_A_BASE, sizeof(a_words));
                Xil_DCacheFlushRange(BRAM_B_BASE, sizeof(b_words));
            }

            write_reg(REG_STREAM_LEN, stream_len);
            write_reg(REG_FLUSH_LEN,  ((u32)tile_count << 16) | (u32)flush_len);
            write_reg(REG_CTRL, 0x2); // clear pulse
            write_reg(REG_CTRL, 0x0);
            write_reg(REG_CTRL, 0x1); // start
            while ((read_reg(REG_STATUS) & 0x1) == 0) {;}
            u8 st = STATUS_OK;
            send_udp_payload(peer_ip, peer_port, &st, 1);
        }
        break;
    case OPC_READ_C:
        if (plen != 0) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
        {
            if (tile_count == 0 || tile_count > MAX_TILE_COUNT) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
            int total_words = tile_count * 16;
            int total_bytes = total_words * 4 + 1; // status + payload
            if (total_bytes > ETH_MAX_FRAME) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
            u8 *out = tx_buf; // payload region
            out[0] = STATUS_OK;
            Xil_DCacheInvalidateRange(BRAM_C_BASE, total_words*4);
            for (int i = 0; i < total_words; i++) {
                u32 v = Xil_In32(BRAM_C_BASE + i*4);
                put_u32le(v, &out[1 + i*4]);
            }
            send_udp_payload(peer_ip, peer_port, out, (u16)total_bytes);
        }
        break;
    case OPC_VERSION:
        if (plen != 0) { u8 st = STATUS_BADLEN; send_udp_payload(peer_ip, peer_port, &st, 1); break; }
        {
            u8 out[5];
            out[0] = STATUS_OK;
            put_u32le(0x0003u, &out[1]);  // protocol version 3
            send_udp_payload(peer_ip, peer_port, out, sizeof(out));
        }
        break;
    default:
        { u8 st = STATUS_BADOP; send_udp_payload(peer_ip, peer_port, &st, 1); }
        break;
    }
}

static void udp_rx(void *arg, struct udp_pcb *pcb, struct pbuf *p,
                   const ip_addr_t *addr, u16_t port) {
    (void)arg;
    (void)pcb;
    if (!p) return;
    if (p->tot_len == 0 || p->tot_len > ETH_MAX_FRAME) { pbuf_free(p); return; }
    if (pbuf_copy_partial(p, rx_buf, p->tot_len, 0) != p->tot_len) { pbuf_free(p); return; }
    handle_rpc(addr, port, rx_buf, (u16)p->tot_len);
    pbuf_free(p);
}

int main(void) {
    xil_printf("Systolic array RPC firmware (lwIP UDP over EthernetLite)\r\n");
    set_leds(0x1);

    lwip_init();

    ip4_addr_t ipaddr, netmask, gw;
    IP4_ADDR(&ipaddr,  ip_addr_bytes[0], ip_addr_bytes[1], ip_addr_bytes[2], ip_addr_bytes[3]);
    IP4_ADDR(&netmask, 255, 255, 255, 0);
    IP4_ADDR(&gw,      ip_addr_bytes[0], ip_addr_bytes[1], ip_addr_bytes[2], 1);

    // Set MAC before bringing interface up
    xemacliteif_setmac(0, (u8 *)mac_addr);

    if (!xemac_add(&netif_data, (ip_addr_t *)&ipaddr, (ip_addr_t *)&netmask, (ip_addr_t *)&gw,
                   (unsigned char *)mac_addr, ETH_BASEADDR)) {
        xil_printf("netif_add failed\r\n");
        set_leds(0xF);
        return -1;
    }
    netif_set_default(&netif_data);
    netif_set_up(&netif_data);

    rpc_pcb = udp_new_ip_type(IPADDR_TYPE_V4);
    if (!rpc_pcb) {
        xil_printf("udp_new failed\r\n");
        set_leds(0xF);
        return -1;
    }
    if (udp_bind(rpc_pcb, IP_ADDR_ANY, UDP_PORT) != ERR_OK) {
        xil_printf("udp_bind failed\r\n");
        set_leds(0xF);
        return -1;
    }
    udp_recv(rpc_pcb, udp_rx, NULL);

    xil_printf("MAC %02x:%02x:%02x:%02x:%02x:%02x IP %d.%d.%d.%d UDP %d\r\n",
               mac_addr[0], mac_addr[1], mac_addr[2], mac_addr[3], mac_addr[4], mac_addr[5],
               ip_addr_bytes[0], ip_addr_bytes[1], ip_addr_bytes[2], ip_addr_bytes[3], UDP_PORT);
    set_leds(0x2);

    u32 blink = 0;
    while (1) {
        xemacif_input(&netif_data); // poll RX/TX
        sys_check_timeouts();       // drive lwIP timers

        // simple heartbeat blink
        if (++blink == 1000000u) {
            blink = 0;
            static u32 led = 0x2;
            led ^= 0x1;
            set_leds(led);
        }
    }
    return 0;
}
