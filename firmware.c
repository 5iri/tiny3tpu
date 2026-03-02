#include "xil_io.h"
#include "xparameters.h"
#include "xiltimer.h"
#include "xtimer_config.h"
#include "xil_printf.h"
#include "xil_exception.h"
#include <string.h>

#if !defined(ENABLE_LWIP_UDP)
#define ENABLE_LWIP_UDP 0U
#endif

#define FW_TRANSPORT_UART     0U
#define FW_TRANSPORT_LWIP_UDP 1U

#if !defined(FW_TRANSPORT_MODE)
#define FW_TRANSPORT_MODE FW_TRANSPORT_UART
#endif

#if ((FW_TRANSPORT_MODE == FW_TRANSPORT_LWIP_UDP) && (ENABLE_LWIP_UDP == 0U))
#error "FW_TRANSPORT_MODE=FW_TRANSPORT_LWIP_UDP requires ENABLE_LWIP_UDP=1 and lwIP BSP support"
#endif

#if ENABLE_LWIP_UDP
#include "lwip/opt.h"
#include "lwip/init.h"
#include "lwip/ip_addr.h"
#include "lwip/ip.h"
#include "lwip/inet_chksum.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"
#include "lwip/timeouts.h"
#include "lwip/prot/ip4.h"
#include "lwip/prot/udp.h"
#include "netif/etharp.h"
#include "netif/ethernet.h"
#include "netif/xadapter.h"
#include "netif/xemacpsif.h"
#include "xemacps_hw.h"
#include "xemac_ieee_reg.h"
#if !defined(SDT)
#include "xscugic.h"
#endif
#endif

#define SYSTOLIC_BASEADDR XPAR_SYSTOLIC_CORE_0_BASEADDR

/* AXI register map (byte offsets). */
#define REG_CTRL          0x00U
#define REG_UBUF_CFG      0x04U
#define REG_UBUF_DATA     0x08U
#define REG_CRD_CFG       0x0CU
#define REG_STATUS        0x10U
#define REG_CRD_DATA_LO   0x14U
#define REG_CRD_DATA_HI   0x18U

/* REG_CTRL bits (pulsed via writes). */
#define CTRL_START_PULSE      (1U << 0)
#define CTRL_UBUF_WR_PULSE    (1U << 1)
#define CTRL_CRD_RD_PULSE     (1U << 2)

/* REG_STATUS bits. */
#define STATUS_BUSY_MASK      (1U << 0)

#define CORE_COUNT 2U
#define TILE_N     4U
#define MAT_N      16U
#define TILES_PER_DIM (MAT_N / TILE_N)

#define MAX_WAIT_POLLS 1000000U
#define REG_WRITE_VERIFY_RETRIES 32U
#define BIN_REQ_MAGIC  0x3154414DU /* "MAT1" */
#define BIN_RESP_MAGIC 0x31505352U /* "RSP1" */
#define BIN_REQ_MODEL_MAGIC 0x31444F4DU /* "MOD1" */
#define BIN_REQ_MODEL_CHUNK_MAGIC 0x3148434DU /* "MCH1" */
#define BIN_REQ_INFER_MAGIC 0x31464E49U /* "INF1" */
#define BIN_RESP_ACK_MAGIC  0x314B4341U /* "ACK1" */
#define BIN_RESP_INFER_MAGIC 0x31445250U /* "PRD1" */
#define MODEL_PROTO_VERSION 0x00020000U
#define I32_MAX_VAL    2147483647LL
#define I32_MIN_VAL   (-2147483647LL - 1LL)
#define MAX_MODEL_DIM 256U
#define MAX_MODEL_LAYERS 16U
#define LEGACY_MODEL_CLASSES 10U
#define MODEL_FLAG_REQUANT (1U << 0)
#define MODEL_FLAG_RELU    (1U << 1)
#define MODEL_FLAG_ALL     (MODEL_FLAG_REQUANT | MODEL_FLAG_RELU)
#define MODEL_CHUNK_FLAG_START (1U << 0)
#define MODEL_CHUNK_FLAG_END   (1U << 1)
#define MODEL_CHUNK_FLAG_ALL   (MODEL_CHUNK_FLAG_START | MODEL_CHUNK_FLAG_END)
#define IO_MODE_UART   0U
#define IO_MODE_BUFFER 1U
#define NET_MAX_PACKET_BYTES 65507U
#define NET_UDP_PORT 9001U
#define NET_IP_ADDR0 192U
#define NET_IP_ADDR1 168U
#define NET_IP_ADDR2 1U
#define NET_IP_ADDR3 77U
#define NET_NETMASK0 255U
#define NET_NETMASK1 255U
#define NET_NETMASK2 255U
#define NET_NETMASK3 0U
#define NET_GW_ADDR0 192U
#define NET_GW_ADDR1 168U
#define NET_GW_ADDR2 1U
#define NET_GW_ADDR3 1U
#define NET_MAC0 0x02U
#define NET_MAC1 0x00U
#define NET_MAC2 0x00U
#define NET_MAC3 0x00U
#define NET_MAC4 0x00U
#define NET_MAC5 0x77U
#define NET_DEBUG_LOG 1U
#define FW_BUILD_ID "udp-debug-arp-fallback-v7-chunked"
#define NET_PHY_ADDR 7U
#define NET_FORCE_PHY_PROFILE_100M 1U
#define NET_ETH_HDR_LEN 14U
#define NET_IPV4_HDR_LEN 20U
#define NET_UDP_HDR_LEN 8U
#define NET_ARP_PKT_LEN 28U
#define NET_ARP_FRAME_LEN (NET_ETH_HDR_LEN + NET_ARP_PKT_LEN)
#define NET_IPV4_MTU 1500U
#define NET_FALLBACK_MAX_UDP_PAYLOAD (NET_IPV4_MTU - NET_IPV4_HDR_LEN - NET_UDP_HDR_LEN)
#define NET_FALLBACK_FRAME_MAX (NET_ETH_HDR_LEN + NET_IPV4_MTU)
#define MAX_MODEL_LAYER_UPLOAD_BYTES (12U + (MAX_MODEL_DIM * MAX_MODEL_DIM) + (4U * MAX_MODEL_DIM))
#define MAX_MODEL_UPLOAD_BYTES (12U + ((MAX_MODEL_LAYERS + 1U) * 4U) + (MAX_MODEL_LAYERS * MAX_MODEL_LAYER_UPLOAD_BYTES))
/*
 * Strict register writeback verification improves robustness on unstable buses,
 * but it is expensive in the inner GEMM loops. Keep it off for performance.
 */
#define MMIO_STRICT_VERIFY 0U

static u32 g_mmio_write_retry_total = 0U;
static u32 g_mmio_write_fail_total = 0U;

/* These static buffers live in system memory (DDR on this platform). */
static s32 g_ddr_a[MAT_N][MAT_N];
static s32 g_ddr_b[MAT_N][MAT_N];
static s64 g_ddr_c_hw[MAT_N][MAT_N];
static s32 g_tile_a[MAT_N][MAT_N];
static s32 g_tile_b[MAT_N][MAT_N];
static s64 g_tile_c[MAT_N][MAT_N];

/* Cached MLP model in DDR-backed buffers (weights stored transposed). */
static u32 g_model_loaded = 0U;
static u32 g_model_layer_count = 0U;
static u32 g_model_dims[MAX_MODEL_LAYERS + 1U];
static s32 g_model_rq_mult[MAX_MODEL_LAYERS];
static u32 g_model_rq_shift[MAX_MODEL_LAYERS];
static u32 g_model_flags[MAX_MODEL_LAYERS];
static s8 g_model_w_t[MAX_MODEL_LAYERS][MAX_MODEL_DIM][MAX_MODEL_DIM];
static s32 g_model_b[MAX_MODEL_LAYERS][MAX_MODEL_DIM];
static s32 g_model_act_a[MAX_MODEL_DIM];
static s32 g_model_act_b[MAX_MODEL_DIM];
static s32 g_model_acc[MAX_MODEL_DIM];
static u32 g_io_mode = IO_MODE_UART;
static const u8 *g_io_rx_buf = (const u8 *)0;
static u32 g_io_rx_len = 0U;
static u32 g_io_rx_pos = 0U;
static u8 *g_io_tx_buf = (u8 *)0;
static u32 g_io_tx_cap = 0U;
static u32 g_io_tx_len = 0U;
static u32 g_io_rx_underflow = 0U;
static u32 g_io_tx_overflow = 0U;

#if ENABLE_LWIP_UDP
static u8 g_model_upload_buf[MAX_MODEL_UPLOAD_BYTES];
static u32 g_model_upload_active = 0U;
static u32 g_model_upload_expected = 0U;
static u32 g_model_upload_received = 0U;
static void reset_model_upload_state(void);
static struct netif g_netif;
static struct udp_pcb *g_udp_pcb = (struct udp_pcb *)0;
static u8 g_net_rx_buf[NET_MAX_PACKET_BYTES];
static u8 g_net_tx_buf[NET_MAX_PACKET_BYTES];
static const u8 g_net_mac[6] = {
	NET_MAC0, NET_MAC1, NET_MAC2, NET_MAC3, NET_MAC4, NET_MAC5
};
static u32 g_udp_rx_pkts = 0U;
static u32 g_udp_tx_ok = 0U;
static u32 g_udp_tx_err = 0U;
static s32 g_udp_last_err = 0;
static u16 g_ipv4_tx_id = 1U;
static u8 g_last_peer_mac[6];
static ip4_addr_t g_last_peer_ip;
static u32 g_last_peer_mac_valid = 0U;
static u8 g_net_l2_frame[NET_FALLBACK_FRAME_MAX];
static u32 g_udp_tx_fallback_ok = 0U;
static u32 g_udp_tx_fallback_err = 0U;

#if defined(__arm__) && !defined(ARMR5) && !defined(SDT)
#define NET_INTC_DEVICE_ID XPAR_SCUGIC_SINGLE_DEVICE_ID
#endif
#endif

static inline void reg_write(u32 offset, u32 value)
{
	Xil_Out32((u32)(SYSTOLIC_BASEADDR + offset), value);
}

static inline u32 reg_read(u32 offset)
{
	return Xil_In32((u32)(SYSTOLIC_BASEADDR + offset));
}

#if MMIO_STRICT_VERIFY
static int reg_write_checked(u32 offset, u32 value)
{
	u32 tries;

	for (tries = 0U; tries < REG_WRITE_VERIFY_RETRIES; ++tries) {
		reg_write(offset, value);
		if (reg_read(offset) == value) {
			g_mmio_write_retry_total += tries;
			return 0;
		}
	}

	++g_mmio_write_fail_total;
	return -1;
}
#endif

static inline int reg_write_hot(u32 offset, u32 value)
{
#if MMIO_STRICT_VERIFY
	return reg_write_checked(offset, value);
#else
	reg_write(offset, value);
	return 0;
#endif
}

static inline int ctrl_pulse(u32 bits)
{
	return reg_write_hot(REG_CTRL, bits);
}

static inline u32 make_ubuf_cfg(u32 select_b, u32 core, u32 row, u32 col)
{
	u32 cfg = 0U;

	cfg |= (select_b & 0x1U) << 0;
	cfg |= (core & 0x1U) << 8;
	cfg |= (row & 0x3U) << 16;
	cfg |= (col & 0x3U) << 24;

	return cfg;
}

static inline u32 make_crd_cfg(u32 core, u32 row, u32 col)
{
	u32 cfg = 0U;

	cfg |= (core & 0x1U) << 8;
	cfg |= (row & 0x3U) << 16;
	cfg |= (col & 0x3U) << 24;

	return cfg;
}

static void io_set_uart_mode(void)
{
	g_io_mode = IO_MODE_UART;
	g_io_rx_buf = (const u8 *)0;
	g_io_rx_len = 0U;
	g_io_rx_pos = 0U;
	g_io_tx_buf = (u8 *)0;
	g_io_tx_cap = 0U;
	g_io_tx_len = 0U;
	g_io_rx_underflow = 0U;
	g_io_tx_overflow = 0U;
}

#if ENABLE_LWIP_UDP
static void net_platform_setup_interrupts(void)
{
#if defined(__arm__) && !defined(ARMR5)
	Xil_ExceptionInit();
#if !defined(SDT)
	XScuGic_DeviceInitialize(NET_INTC_DEVICE_ID);
	Xil_ExceptionRegisterHandler(
		XIL_EXCEPTION_ID_IRQ_INT,
		(Xil_ExceptionHandler)XScuGic_DeviceInterruptHandler,
		(void *)NET_INTC_DEVICE_ID
	);
#endif
#endif
}

static void net_platform_enable_interrupts(void)
{
	Xil_ExceptionEnableMask(XIL_EXCEPTION_IRQ);
}

static XEmacPs *net_get_emacps(void)
{
	struct xemac_s *xemac = (struct xemac_s *)g_netif.state;
	xemacpsif_s *xemacps;
	if ((xemac == (struct xemac_s *)0) || (xemac->state == (void *)0)) {
		return (XEmacPs *)0;
	}
	xemacps = (xemacpsif_s *)xemac->state;
	return &xemacps->emacps;
}

static void net_force_emac_runtime_config(void)
{
	XEmacPs *emac = net_get_emacps();
	u32 nwctrl;
	u32 ncfg;

	if (emac == (XEmacPs *)0) {
		return;
	}
	(void)XEmacPs_SetOptions(
		emac,
		XEMACPS_TRANSMITTER_ENABLE_OPTION |
		XEMACPS_RECEIVER_ENABLE_OPTION |
		XEMACPS_BROADCAST_OPTION |
		XEMACPS_MULTICAST_OPTION |
		XEMACPS_PROMISC_OPTION
	);
	nwctrl = XEmacPs_ReadReg(emac->Config.BaseAddress, XEMACPS_NWCTRL_OFFSET);
	nwctrl |= (XEMACPS_NWCTRL_TXEN_MASK | XEMACPS_NWCTRL_RXEN_MASK);
	XEmacPs_WriteReg(emac->Config.BaseAddress, XEMACPS_NWCTRL_OFFSET, nwctrl);
	ncfg = XEmacPs_ReadReg(emac->Config.BaseAddress, XEMACPS_NWCFG_OFFSET);
	xil_printf(
		"ETH GEM cfg base=0x%08x nwctrl=0x%08x nwcfg=0x%08x\r\n",
		(unsigned)emac->Config.BaseAddress,
		(unsigned)nwctrl,
		(unsigned)ncfg
	);
}

static void net_small_delay(u32 loops)
{
	volatile u32 i;
	for (i = 0U; i < loops; ++i) {
	}
}

static void net_force_phy_profile(void)
{
#if NET_FORCE_PHY_PROFILE_100M
	XEmacPs *emac = net_get_emacps();
	u16 regv = 0U;
	u16 status = 0U;
	u16 spec = 0U;
	if (emac == (XEmacPs *)0) {
		return;
	}

	/* Keep Marvell RGMII skew programming from Xilinx path. */
	(void)XEmacPs_PhyWrite(emac, NET_PHY_ADDR, IEEE_PAGE_ADDRESS_REGISTER, 2U);
	if (XEmacPs_PhyRead(emac, NET_PHY_ADDR, IEEE_CONTROL_REG_MAC, &regv) == XST_SUCCESS) {
		regv |= IEEE_RGMII_TXRX_CLOCK_DELAYED_MASK;
		(void)XEmacPs_PhyWrite(emac, NET_PHY_ADDR, IEEE_CONTROL_REG_MAC, regv);
	}
	(void)XEmacPs_PhyWrite(emac, NET_PHY_ADDR, IEEE_PAGE_ADDRESS_REGISTER, 0U);

	/* Advertise only 100M (disable 10M + 1G advert), then restart AN. */
	if (XEmacPs_PhyRead(emac, NET_PHY_ADDR, IEEE_AUTONEGO_ADVERTISE_REG, &regv) == XST_SUCCESS) {
		regv |= (IEEE_ASYMMETRIC_PAUSE_MASK | IEEE_PAUSE_MASK | ADVERTISE_100);
		regv &= (u16)(~ADVERTISE_10);
		(void)XEmacPs_PhyWrite(emac, NET_PHY_ADDR, IEEE_AUTONEGO_ADVERTISE_REG, regv);
	}
	if (XEmacPs_PhyRead(emac, NET_PHY_ADDR, IEEE_1000_ADVERTISE_REG_OFFSET, &regv) == XST_SUCCESS) {
		regv &= (u16)(~ADVERTISE_1000);
		(void)XEmacPs_PhyWrite(emac, NET_PHY_ADDR, IEEE_1000_ADVERTISE_REG_OFFSET, regv);
	}
	if (XEmacPs_PhyRead(emac, NET_PHY_ADDR, IEEE_CONTROL_REG_OFFSET, &regv) == XST_SUCCESS) {
		regv |= (IEEE_CTRL_AUTONEGOTIATE_ENABLE | IEEE_STAT_AUTONEGOTIATE_RESTART);
		regv &= (u16)(~IEEE_CTRL_1GBPS_LINKSPEED_MASK);
		regv |= IEEE_CTRL_LINKSPEED_100M;
		(void)XEmacPs_PhyWrite(emac, NET_PHY_ADDR, IEEE_CONTROL_REG_OFFSET, regv);
	}

	/* Match GEM MAC speed to the forced profile. */
	XEmacPs_SetOperatingSpeed(emac, 100U);
	net_small_delay(200000U);
	(void)XEmacPs_PhyRead(emac, NET_PHY_ADDR, IEEE_STATUS_REG_OFFSET, &status);
	(void)XEmacPs_PhyRead(emac, NET_PHY_ADDR, IEEE_SPECIFIC_STATUS_REG, &spec);
	xil_printf(
		"ETH PHY forced addr=%u profile=100M status=0x%04x spec=0x%04x\r\n",
		(unsigned)NET_PHY_ADDR,
		(unsigned)status,
		(unsigned)spec
	);
#endif
}

static void io_set_buffer_mode(const u8 *rx_buf, u32 rx_len, u8 *tx_buf, u32 tx_cap)
{
	g_io_mode = IO_MODE_BUFFER;
	g_io_rx_buf = rx_buf;
	g_io_rx_len = rx_len;
	g_io_rx_pos = 0U;
	g_io_tx_buf = tx_buf;
	g_io_tx_cap = tx_cap;
	g_io_tx_len = 0U;
	g_io_rx_underflow = 0U;
	g_io_tx_overflow = 0U;
}

typedef struct {
	u32 mode;
	const u8 *rx_buf;
	u32 rx_len;
	u32 rx_pos;
	u8 *tx_buf;
	u32 tx_cap;
	u32 tx_len;
	u32 rx_underflow;
	u32 tx_overflow;
} io_state_snapshot_t;

static void io_save_state(io_state_snapshot_t *snap)
{
	if (snap == (io_state_snapshot_t *)0) {
		return;
	}
	snap->mode = g_io_mode;
	snap->rx_buf = g_io_rx_buf;
	snap->rx_len = g_io_rx_len;
	snap->rx_pos = g_io_rx_pos;
	snap->tx_buf = g_io_tx_buf;
	snap->tx_cap = g_io_tx_cap;
	snap->tx_len = g_io_tx_len;
	snap->rx_underflow = g_io_rx_underflow;
	snap->tx_overflow = g_io_tx_overflow;
}

static void io_restore_state(const io_state_snapshot_t *snap)
{
	if (snap == (const io_state_snapshot_t *)0) {
		return;
	}
	g_io_mode = snap->mode;
	g_io_rx_buf = snap->rx_buf;
	g_io_rx_len = snap->rx_len;
	g_io_rx_pos = snap->rx_pos;
	g_io_tx_buf = snap->tx_buf;
	g_io_tx_cap = snap->tx_cap;
	g_io_tx_len = snap->tx_len;
	g_io_rx_underflow = snap->rx_underflow;
	g_io_tx_overflow = snap->tx_overflow;
}
#endif

static inline void io_write_u8(u8 v)
{
	if (g_io_mode == IO_MODE_BUFFER) {
		if ((g_io_tx_buf != (u8 *)0) && (g_io_tx_len < g_io_tx_cap)) {
			g_io_tx_buf[g_io_tx_len] = v;
			++g_io_tx_len;
		} else {
			g_io_tx_overflow = 1U;
		}
	} else {
		outbyte((char)v);
	}
}

static inline u8 uart_read_u8(void)
{
	if (g_io_mode == IO_MODE_BUFFER) {
		if ((g_io_rx_buf == (const u8 *)0) || (g_io_rx_pos >= g_io_rx_len)) {
			g_io_rx_underflow = 1U;
			return 0U;
		}
		return g_io_rx_buf[g_io_rx_pos++];
	}
	return (u8)inbyte();
}

static u32 uart_read_u32_le(void)
{
	u32 b0 = (u32)uart_read_u8();
	u32 b1 = (u32)uart_read_u8();
	u32 b2 = (u32)uart_read_u8();
	u32 b3 = (u32)uart_read_u8();

	return b0 | (b1 << 8) | (b2 << 16) | (b3 << 24);
}

static s32 uart_read_s32_le(void)
{
	return (s32)uart_read_u32_le();
}

static void uart_read_s32_array_le(s32 *dst, u32 count)
{
	u32 i;
	for (i = 0U; i < count; ++i) {
		dst[i] = uart_read_s32_le();
	}
}

static s8 uart_read_s8(void)
{
	return (s8)uart_read_u8();
}

static void uart_read_matrix_s8_to_s32(s32 m[MAT_N][MAT_N])
{
	u32 i;
	u32 j;

	for (i = 0U; i < MAT_N; ++i) {
		for (j = 0U; j < MAT_N; ++j) {
			m[i][j] = (s32)uart_read_s8();
		}
	}
}

static void uart_write_u32_le(u32 v)
{
	io_write_u8((u8)(v & 0xFFU));
	io_write_u8((u8)((v >> 8) & 0xFFU));
	io_write_u8((u8)((v >> 16) & 0xFFU));
	io_write_u8((u8)((v >> 24) & 0xFFU));
}

static void uart_write_s32_le(s32 v)
{
	uart_write_u32_le((u32)v);
}

static void uart_write_u64_le(u64 v)
{
	uart_write_u32_le((u32)(v & 0xFFFFFFFFU));
	uart_write_u32_le((u32)((v >> 32) & 0xFFFFFFFFU));
}

static s32 saturate_i32_from_i64(s64 v)
{
	if (v > (s64)I32_MAX_VAL) {
		return (s32)I32_MAX_VAL;
	}
	if (v < (s64)I32_MIN_VAL) {
		return (s32)I32_MIN_VAL;
	}
	return (s32)v;
}

static u32 uart_wait_for_any_req_magic(void)
{
	u32 window = 0U;
	if (g_io_mode == IO_MODE_BUFFER) {
		while (g_io_rx_pos < g_io_rx_len) {
			u8 b = uart_read_u8();
			window = (window >> 8) | ((u32)b << 24);
			if ((window == BIN_REQ_MAGIC) || (window == BIN_REQ_MODEL_MAGIC) ||
			    (window == BIN_REQ_MODEL_CHUNK_MAGIC) || (window == BIN_REQ_INFER_MAGIC)) {
				return window;
			}
		}
		return 0U;
	}

	while (1) {
		u8 b = uart_read_u8();
		window = (window >> 8) | ((u32)b << 24);
		if ((window == BIN_REQ_MAGIC) || (window == BIN_REQ_MODEL_MAGIC) ||
		    (window == BIN_REQ_MODEL_CHUNK_MAGIC) || (window == BIN_REQ_INFER_MAGIC)) {
			return window;
		}
	}
}

static int accel_write_operand(u32 core, u32 row, u32 col, u32 select_b, s32 data)
{
	if (reg_write_hot(REG_UBUF_CFG, make_ubuf_cfg(select_b, core, row, col)) != 0) {
		return -1;
	}
	if (reg_write_hot(REG_UBUF_DATA, (u32)data) != 0) {
		return -1;
	}
	if (ctrl_pulse(CTRL_UBUF_WR_PULSE) != 0) {
		return -1;
	}

	return 0;
}

static int accel_read_result_cell(u32 core, u32 row, u32 col, s64 *out_val)
{
	u32 lo;
	u32 hi;

	if (reg_write_hot(REG_CRD_CFG, make_crd_cfg(core, row, col)) != 0) {
		return -1;
	}
	if (ctrl_pulse(CTRL_CRD_RD_PULSE) != 0) {
		return -1;
	}
	/* Let one AXI read elapse so RTL can latch C data on c_rd_en pulse. */
	(void)reg_read(REG_STATUS);

	lo = reg_read(REG_CRD_DATA_LO);
	hi = reg_read(REG_CRD_DATA_HI);

	*out_val = ((s64)(s32)hi << 32) | (s64)lo;
	return 0;
}

static int accel_wait_until_idle(u32 timeout_polls)
{
	u32 busy_seen = 0U;

	while (timeout_polls > 0U) {
		u32 status = reg_read(REG_STATUS);
		u32 busy = status & STATUS_BUSY_MASK;

		if (busy != 0U) {
			busy_seen = 1U;
		}
		if ((busy_seen != 0U) && (busy == 0U)) {
			return 0;
		}
		--timeout_polls;
	}

	return -1;
}

static int load_zero_tile_to_core(u32 core)
{
	u32 r;
	u32 c;

	for (r = 0U; r < TILE_N; ++r) {
		for (c = 0U; c < TILE_N; ++c) {
			if (accel_write_operand(core, r, c, 0U, 0) != 0) {
				return -1;
			}
		}
	}
	for (r = 0U; r < TILE_N; ++r) {
		for (c = 0U; c < TILE_N; ++c) {
			if (accel_write_operand(core, r, c, 1U, 0) != 0) {
				return -1;
			}
		}
	}

	return 0;
}

static int load_a_tile_to_core(
	u32 core,
	const s32 a[MAT_N][MAT_N],
	u32 tile_r,
	u32 tile_k
)
{
	u32 r;
	u32 c;
	u32 ar = tile_r * TILE_N;
	u32 ak = tile_k * TILE_N;

	for (r = 0U; r < TILE_N; ++r) {
		for (c = 0U; c < TILE_N; ++c) {
			if (accel_write_operand(core, r, c, 0U, a[ar + r][ak + c]) != 0) {
				return -1;
			}
		}
	}

	return 0;
}

static int load_b_tile_to_core(
	u32 core,
	const s32 b[MAT_N][MAT_N],
	u32 tile_k,
	u32 tile_c
)
{
	u32 r;
	u32 c;
	u32 bk = tile_k * TILE_N;
	u32 bc = tile_c * TILE_N;

	for (r = 0U; r < TILE_N; ++r) {
		for (c = 0U; c < TILE_N; ++c) {
			if (accel_write_operand(core, r, c, 1U, b[bk + r][bc + c]) != 0) {
				return -1;
			}
		}
	}

	return 0;
}

static int accumulate_core_result_to_matrix(
	u32 core,
	s64 c[MAT_N][MAT_N],
	u32 tile_r,
	u32 tile_c
)
{
	u32 r;
	u32 col;
	u32 dst_r = tile_r * TILE_N;
	u32 dst_c = tile_c * TILE_N;

	for (r = 0U; r < TILE_N; ++r) {
		for (col = 0U; col < TILE_N; ++col) {
			s64 val = 0;
			if (accel_read_result_cell(core, r, col, &val) != 0) {
				return -1;
			}
			c[dst_r + r][dst_c + col] += val;
		}
	}

	return 0;
}

static int matmul_hw_dual_core(
	const s32 a[MAT_N][MAT_N],
	const s32 b[MAT_N][MAT_N],
	s64 c[MAT_N][MAT_N]
)
{
	u32 tile_r;
	u32 tile_k_base;
	u32 i;
	u32 j;

	/* Shared output buffer in DDR: clear once, then accumulate partial tiles. */
	for (i = 0U; i < MAT_N; ++i) {
		for (j = 0U; j < MAT_N; ++j) {
			c[i][j] = 0;
		}
	}

	for (tile_r = 0U; tile_r < TILES_PER_DIM; ++tile_r) {
		for (tile_k_base = 0U; tile_k_base < TILES_PER_DIM; tile_k_base += CORE_COUNT) {
			u32 core;
			u32 tile_k_for_core[CORE_COUNT];
			u32 tile_c;

			/*
			 * Scratchpad-aware schedule:
			 * 1) Load A once per core for this (tile_r, tile_k) pair.
			 * 2) Sweep all tile_c by only loading B per core, run, accumulate.
			 * This reduces A-side MMIO traffic by ~4x for 16x16/4x4 tiling.
			 */
			for (core = 0U; core < CORE_COUNT; ++core) {
				u32 tk = tile_k_base + core;
				tile_k_for_core[core] = tk;

				if (tk < TILES_PER_DIM) {
					if (load_a_tile_to_core(core, a, tile_r, tk) != 0) {
						return -2;
					}
				} else {
					if (load_zero_tile_to_core(core) != 0) {
						return -3;
					}
				}
			}

			for (tile_c = 0U; tile_c < TILES_PER_DIM; ++tile_c) {
				for (core = 0U; core < CORE_COUNT; ++core) {
					if (tile_k_for_core[core] < TILES_PER_DIM) {
						if (load_b_tile_to_core(core, b, tile_k_for_core[core], tile_c) != 0) {
							return -4;
						}
					}
				}

				if (ctrl_pulse(CTRL_START_PULSE) != 0) {
					return -5;
				}
				if (accel_wait_until_idle(MAX_WAIT_POLLS) != 0) {
					return -6;
				}

				for (core = 0U; core < CORE_COUNT; ++core) {
					if (tile_k_for_core[core] < TILES_PER_DIM) {
						if (accumulate_core_result_to_matrix(core, c, tile_r, tile_c) != 0) {
							return -7;
						}
					}
				}
			}
		}
	}

	return 0;
}

static int matvec_hw_1xk_kxn(
	const s32 *avec,
	u32 k,
	const s8 *b_kxn,
	u32 n,
	u32 b_row_stride,
	s32 *out,
	u32 *packet_counter
)
{
	u32 n0;
	u32 i;

	for (i = 0U; i < n; ++i) {
		out[i] = 0;
	}

	for (n0 = 0U; n0 < n; n0 += MAT_N) {
		u32 jn = (n - n0 < MAT_N) ? (n - n0) : MAT_N;
		s32 partial[MAT_N];
		u32 k0;
		u32 j;

		for (j = 0U; j < MAT_N; ++j) {
			partial[j] = 0;
		}

		for (k0 = 0U; k0 < k; k0 += MAT_N) {
			u32 kk = (k - k0 < MAT_N) ? (k - k0) : MAT_N;
			u32 r;
			u32 c;
			int rc;

			for (r = 0U; r < MAT_N; ++r) {
				for (c = 0U; c < MAT_N; ++c) {
					g_tile_a[r][c] = 0;
					g_tile_b[r][c] = 0;
				}
			}

			for (c = 0U; c < kk; ++c) {
				g_tile_a[0U][c] = avec[k0 + c];
			}
			for (r = 0U; r < kk; ++r) {
				for (c = 0U; c < jn; ++c) {
					g_tile_b[r][c] = (s32)b_kxn[(k0 + r) * b_row_stride + (n0 + c)];
				}
			}

			rc = matmul_hw_dual_core(g_tile_a, g_tile_b, g_tile_c);
			if (rc != 0) {
				return rc;
			}
			if (packet_counter != (u32 *)0) {
				++(*packet_counter);
			}

			for (c = 0U; c < jn; ++c) {
				partial[c] += saturate_i32_from_i64(g_tile_c[0U][c]);
			}
		}

		for (j = 0U; j < jn; ++j) {
			out[n0 + j] = partial[j];
		}
	}

	return 0;
}

static s32 requant_i8(s32 acc_with_bias, s32 mult, u32 shift, u32 apply_relu)
{
	s64 prod = (s64)acc_with_bias * (s64)mult;
	s64 q;

	if (shift > 0U) {
		s64 rnd = (prod >= 0) ? ((s64)1 << (shift - 1U)) : -((s64)1 << (shift - 1U));
		q = (prod + rnd) >> shift;
	} else {
		q = prod;
	}

	if ((apply_relu != 0U) && (q < 0)) {
		q = 0;
	}
	if (q > 127) {
		return 127;
	}
	if (q < -128) {
		return -128;
	}
	return (s32)q;
}

static void clear_model_state(void)
{
	g_model_loaded = 0U;
	g_model_layer_count = 0U;
#if ENABLE_LWIP_UDP
	reset_model_upload_state();
#endif
}

static s32 handle_model_load_request_legacy(u32 input_dim)
{
	u32 hidden_dim = uart_read_u32_le();
	s32 rq_mult = uart_read_s32_le();
	u32 rq_shift = uart_read_u32_le();
	u32 o;
	u32 i;

	if ((input_dim == 0U) || (hidden_dim == 0U) ||
	    (input_dim > MAX_MODEL_DIM) || (hidden_dim > MAX_MODEL_DIM) ||
	    (rq_shift > 62U) || (LEGACY_MODEL_CLASSES > MAX_MODEL_DIM)) {
		clear_model_state();
		return -20;
	}

	g_model_layer_count = 2U;
	g_model_dims[0U] = input_dim;
	g_model_dims[1U] = hidden_dim;
	g_model_dims[2U] = LEGACY_MODEL_CLASSES;

	g_model_rq_mult[0U] = rq_mult;
	g_model_rq_shift[0U] = rq_shift;
	g_model_flags[0U] = MODEL_FLAG_REQUANT | MODEL_FLAG_RELU;
	g_model_rq_mult[1U] = 0;
	g_model_rq_shift[1U] = 0U;
	g_model_flags[1U] = 0U;

	/* Incoming W0 is [hidden][input], store transposed as [input][hidden]. */
	for (o = 0U; o < hidden_dim; ++o) {
		for (i = 0U; i < input_dim; ++i) {
			g_model_w_t[0U][i][o] = uart_read_s8();
		}
	}
	uart_read_s32_array_le(g_model_b[0U], hidden_dim);

	/* Incoming W1 is [10][hidden], store transposed as [hidden][10]. */
	for (o = 0U; o < LEGACY_MODEL_CLASSES; ++o) {
		for (i = 0U; i < hidden_dim; ++i) {
			g_model_w_t[1U][i][o] = uart_read_s8();
		}
	}
	uart_read_s32_array_le(g_model_b[1U], LEGACY_MODEL_CLASSES);

	g_model_loaded = 1U;
	return 0;
}

static s32 handle_model_load_request(void)
{
	u32 proto_or_input_dim = uart_read_u32_le();
	u32 layer_count;
	u32 i;
	u32 li;

	if (proto_or_input_dim <= MAX_MODEL_DIM) {
		return handle_model_load_request_legacy(proto_or_input_dim);
	}
	if (proto_or_input_dim != MODEL_PROTO_VERSION) {
		clear_model_state();
		return -21;
	}

	layer_count = uart_read_u32_le();
	if ((layer_count == 0U) || (layer_count > MAX_MODEL_LAYERS)) {
		clear_model_state();
		return -22;
	}

	for (i = 0U; i <= layer_count; ++i) {
		u32 dim = uart_read_u32_le();
		if ((dim == 0U) || (dim > MAX_MODEL_DIM)) {
			clear_model_state();
			return -23;
		}
		g_model_dims[i] = dim;
	}

	for (li = 0U; li < layer_count; ++li) {
		u32 in_dim = g_model_dims[li];
		u32 out_dim = g_model_dims[li + 1U];
		s32 rq_mult = uart_read_s32_le();
		u32 rq_shift = uart_read_u32_le();
		u32 flags = uart_read_u32_le();
		u32 o;

		if ((rq_shift > 62U) || ((flags & (~MODEL_FLAG_ALL)) != 0U)) {
			clear_model_state();
			return -24;
		}
		if (((li + 1U) < layer_count) && ((flags & MODEL_FLAG_REQUANT) == 0U)) {
			/* Hidden layers must emit quantized activations for next layer input. */
			clear_model_state();
			return -25;
		}

		g_model_rq_mult[li] = rq_mult;
		g_model_rq_shift[li] = rq_shift;
		g_model_flags[li] = flags;

		for (o = 0U; o < out_dim; ++o) {
			for (i = 0U; i < in_dim; ++i) {
				g_model_w_t[li][i][o] = uart_read_s8();
			}
		}
		uart_read_s32_array_le(g_model_b[li], out_dim);
	}

	g_model_layer_count = layer_count;
	g_model_loaded = 1U;
	return 0;
}

#if ENABLE_LWIP_UDP
static void reset_model_upload_state(void)
{
	g_model_upload_active = 0U;
	g_model_upload_expected = 0U;
	g_model_upload_received = 0U;
}

static u32 read_u32_le_bytes(const u8 *p)
{
	return ((u32)p[0]) |
	       (((u32)p[1]) << 8U) |
	       (((u32)p[2]) << 16U) |
	       (((u32)p[3]) << 24U);
}

static s32 load_model_blob_preserve_io(const u8 *blob, u32 blob_len)
{
	io_state_snapshot_t saved;
	s32 st;

	if ((blob == (const u8 *)0) || (blob_len < 4U)) {
		return -60;
	}
	if (read_u32_le_bytes(blob) != BIN_REQ_MODEL_MAGIC) {
		return -61;
	}

	io_save_state(&saved);
	io_set_buffer_mode(blob + 4U, blob_len - 4U, (u8 *)0, 0U);
	st = handle_model_load_request();
	if ((st == 0) && (g_io_rx_underflow != 0U)) {
		st = -62;
	}
	io_restore_state(&saved);
	return st;
}

static s32 handle_model_chunk_request(void)
{
	u32 total_len = uart_read_u32_le();
	u32 offset = uart_read_u32_le();
	u32 chunk_len = uart_read_u32_le();
	u32 flags = uart_read_u32_le();
	u32 i;

	if ((flags & (~MODEL_CHUNK_FLAG_ALL)) != 0U) {
		reset_model_upload_state();
		return -63;
	}
	if ((total_len == 0U) || (total_len > MAX_MODEL_UPLOAD_BYTES)) {
		reset_model_upload_state();
		return -64;
	}
	if ((offset > total_len) || (chunk_len > total_len) || (offset > (total_len - chunk_len))) {
		reset_model_upload_state();
		return -65;
	}
	if ((flags & MODEL_CHUNK_FLAG_START) != 0U) {
		if (offset != 0U) {
			reset_model_upload_state();
			return -66;
		}
		g_model_upload_active = 1U;
		g_model_upload_expected = total_len;
		g_model_upload_received = 0U;
	}
	if ((g_model_upload_active == 0U) || (g_model_upload_expected != total_len)) {
		reset_model_upload_state();
		return -67;
	}
	if (offset != g_model_upload_received) {
		return -68;
	}

	for (i = 0U; i < chunk_len; ++i) {
		g_model_upload_buf[offset + i] = uart_read_u8();
	}
	if (g_io_rx_underflow != 0U) {
		reset_model_upload_state();
		return -69;
	}

	g_model_upload_received += chunk_len;
	if (((flags & MODEL_CHUNK_FLAG_END) != 0U) ||
	    (g_model_upload_received == g_model_upload_expected)) {
		s32 st;
		if (g_model_upload_received != g_model_upload_expected) {
			reset_model_upload_state();
			return -70;
		}
		st = load_model_blob_preserve_io(g_model_upload_buf, g_model_upload_expected);
		reset_model_upload_state();
		return st;
	}

	return 0;
}
#endif

static void send_ack_response(s32 status)
{
	uart_write_u32_le(BIN_RESP_ACK_MAGIC);
	uart_write_s32_le(status);
}

static void send_infer_response(
	s32 status,
	u64 hw_cycles,
	u32 hw_packets,
	s32 pred,
	const s32 *logits,
	u32 logits_count
)
{
	u32 i;

	if ((status != 0) || (logits == (const s32 *)0) || (logits_count > MAX_MODEL_DIM)) {
		logits_count = 0U;
	}

	uart_write_u32_le(BIN_RESP_INFER_MAGIC);
	uart_write_s32_le(status);
	uart_write_u64_le(hw_cycles);
	uart_write_u64_le((u64)COUNTS_PER_SECOND);
	uart_write_u32_le(hw_packets);
	uart_write_s32_le(pred);
	uart_write_u32_le(logits_count);
	for (i = 0U; i < logits_count; ++i) {
		uart_write_s32_le(logits[i]);
	}
}

static s32 handle_model_infer_request(
	u64 *out_cycles,
	u32 *out_packets,
	s32 *out_pred,
	s32 out_logits[MAX_MODEL_DIM],
	u32 *out_logits_count
)
{
	u32 packets = 0U;
	u32 i;
	u32 li;
	XTime t0 = 0;
	XTime t1 = 0;
	s32 *act_in = g_model_act_a;
	s32 *act_out = g_model_act_b;

	*out_logits_count = 0U;
	*out_pred = -1;

	if ((g_model_loaded == 0U) || (g_model_layer_count == 0U)) {
		return -30;
	}
	if ((g_model_dims[0U] == 0U) || (g_model_dims[g_model_layer_count] == 0U)) {
		return -31;
	}

	for (i = 0U; i < g_model_dims[0U]; ++i) {
		act_in[i] = (s32)uart_read_s8();
	}

	g_mmio_write_retry_total = 0U;
	g_mmio_write_fail_total = 0U;

	XTime_GetTime(&t0);
	for (li = 0U; li < g_model_layer_count; ++li) {
		u32 in_dim = g_model_dims[li];
		u32 out_dim = g_model_dims[li + 1U];
		u32 flags = g_model_flags[li];
		int rc = matvec_hw_1xk_kxn(
			act_in,
			in_dim,
			&g_model_w_t[li][0][0],
			out_dim,
			MAX_MODEL_DIM,
			g_model_acc,
			&packets
		);

		if (rc != 0) {
			return (s32)rc;
		}

		if ((li + 1U) < g_model_layer_count) {
			for (i = 0U; i < out_dim; ++i) {
				s32 acc_b = g_model_acc[i] + g_model_b[li][i];
				act_out[i] = requant_i8(
					acc_b,
					g_model_rq_mult[li],
					g_model_rq_shift[li],
					(flags & MODEL_FLAG_RELU)
				);
			}

			{
				s32 *tmp = act_in;
				act_in = act_out;
				act_out = tmp;
			}
		} else {
			if ((flags & MODEL_FLAG_REQUANT) != 0U) {
				for (i = 0U; i < out_dim; ++i) {
					s32 acc_b = g_model_acc[i] + g_model_b[li][i];
					out_logits[i] = requant_i8(
						acc_b,
						g_model_rq_mult[li],
						g_model_rq_shift[li],
						(flags & MODEL_FLAG_RELU)
					);
				}
			} else {
				for (i = 0U; i < out_dim; ++i) {
					out_logits[i] = g_model_acc[i] + g_model_b[li][i];
				}
			}
			*out_logits_count = out_dim;
		}
	}
	XTime_GetTime(&t1);

	if (*out_logits_count > 0U) {
		s32 best_idx = 0;
		s32 best_val = out_logits[0];

		for (i = 1U; i < *out_logits_count; ++i) {
			if (out_logits[i] > best_val) {
				best_val = out_logits[i];
				best_idx = (s32)i;
			}
		}
		*out_pred = best_idx;
	}

	*out_packets = packets;
	*out_cycles = (u64)(t1 - t0);
	return 0;
}

static s64 shift_i64(s64 v, s32 shift)
{
	if (shift > 63) {
		shift = 63;
	} else if (shift < -63) {
		shift = -63;
	}

	if (shift > 0) {
		return v >> (u32)shift;
	}
	if (shift < 0) {
		return v << (u32)(-shift);
	}
	return v;
}

static void send_binary_response(s32 status, s32 shift, u64 hw_cycles)
{
	u32 i;
	u32 j;

	uart_write_u32_le(BIN_RESP_MAGIC);
	uart_write_s32_le(status);
	uart_write_u64_le(hw_cycles);
	uart_write_u64_le((u64)COUNTS_PER_SECOND);
	uart_write_u32_le(g_mmio_write_retry_total);
	uart_write_u32_le(g_mmio_write_fail_total);

	for (i = 0U; i < MAT_N; ++i) {
		for (j = 0U; j < MAT_N; ++j) {
			s64 out_val = 0;
			if (status == 0) {
				out_val = shift_i64(g_ddr_c_hw[i][j], shift);
			}
			uart_write_s32_le(saturate_i32_from_i64(out_val));
		}
	}
}

static void handle_gemm_request_binary(void)
{
	s32 shift = 0;
	XTime t0 = 0;
	XTime t1 = 0;
	s32 status = 0;

	shift = uart_read_s32_le();
	uart_read_matrix_s8_to_s32(g_ddr_a);
	uart_read_matrix_s8_to_s32(g_ddr_b);

	g_mmio_write_retry_total = 0U;
	g_mmio_write_fail_total = 0U;

	XTime_GetTime(&t0);
	status = (s32)matmul_hw_dual_core(g_ddr_a, g_ddr_b, g_ddr_c_hw);
	XTime_GetTime(&t1);

	send_binary_response(status, shift, (u64)(t1 - t0));
}

static void process_request_by_magic(u32 req)
{
	if (req == BIN_REQ_MAGIC) {
		handle_gemm_request_binary();
	} else if (req == BIN_REQ_MODEL_MAGIC) {
		s32 st = handle_model_load_request();
		send_ack_response(st);
	} else if (req == BIN_REQ_MODEL_CHUNK_MAGIC) {
#if ENABLE_LWIP_UDP
		s32 st = handle_model_chunk_request();
		send_ack_response(st);
#else
		send_ack_response(-90);
#endif
	} else if (req == BIN_REQ_INFER_MAGIC) {
		u64 cycles = 0U;
		u32 packets = 0U;
		s32 pred = -1;
		u32 logits_count = 0U;
		s32 logits[MAX_MODEL_DIM];
		s32 st = handle_model_infer_request(&cycles, &packets, &pred, logits, &logits_count);
		send_infer_response(st, cycles, packets, pred, logits, logits_count);
	}
}

static s32 process_request_once(void)
{
	u32 req = uart_wait_for_any_req_magic();
	if (req == 0U) {
		return -1;
	}

	process_request_by_magic(req);

	if (g_io_rx_underflow != 0U) {
		return -2;
	}
	if (g_io_tx_overflow != 0U) {
		return -3;
	}
	return 0;
}

#if ENABLE_LWIP_UDP
static inline void write_be16(u8 *dst, u16 v)
{
	dst[0] = (u8)((v >> 8U) & 0xFFU);
	dst[1] = (u8)(v & 0xFFU);
}

static u16 ipv4_hdr_checksum_20(const u8 *hdr)
{
	u32 sum = 0U;
	u32 i;

	for (i = 0U; i < NET_IPV4_HDR_LEN; i += 2U) {
		sum += (((u32)hdr[i]) << 8U) | (u32)hdr[i + 1U];
	}
	while ((sum >> 16U) != 0U) {
		sum = (sum & 0xFFFFU) + (sum >> 16U);
	}
	return (u16)(~sum & 0xFFFFU);
}

static err_t net_send_l2_frame(const u8 *frame, u16 frame_len)
{
	struct pbuf *pb;
	err_t e;
	err_t pe;
	if ((frame == (const u8 *)0) || (frame_len < NET_ETH_HDR_LEN)) {
		return ERR_ARG;
	}
	pb = pbuf_alloc(PBUF_RAW, frame_len, PBUF_RAM);
	if (pb == (struct pbuf *)0) {
		return ERR_MEM;
	}
	pe = pbuf_take(pb, frame, frame_len);
	if (pe == ERR_OK) {
		e = g_netif.linkoutput(&g_netif, pb);
	} else {
		e = pe;
	}
	pbuf_free(pb);
	return e;
}

static void net_try_reply_arp_request(struct pbuf *p, struct netif *inp)
{
	u8 req[NET_ARP_FRAME_LEN];
	u8 *rep = g_net_l2_frame;
	const ip4_addr_t *local_ip;
	if ((p == (struct pbuf *)0) || (inp == (struct netif *)0)) {
		return;
	}
	if (p->tot_len < NET_ARP_FRAME_LEN) {
		return;
	}
	if (pbuf_copy_partial(p, req, NET_ARP_FRAME_LEN, 0U) != NET_ARP_FRAME_LEN) {
		return;
	}
	if ((req[12] != 0x08U) || (req[13] != 0x06U)) {
		return;
	}
	if ((req[14] != 0x00U) || (req[15] != 0x01U) ||
		(req[16] != 0x08U) || (req[17] != 0x00U) ||
		(req[18] != 0x06U) || (req[19] != 0x04U) ||
		(req[20] != 0x00U) || (req[21] != 0x01U)) {
		return;
	}
	local_ip = netif_ip4_addr(inp);
	if ((req[38] != (u8)ip4_addr1_val(*local_ip)) ||
		(req[39] != (u8)ip4_addr2_val(*local_ip)) ||
		(req[40] != (u8)ip4_addr3_val(*local_ip)) ||
		(req[41] != (u8)ip4_addr4_val(*local_ip))) {
		return;
	}

	/* Cache sender as latest peer for fallback unicast path. */
	g_last_peer_mac[0] = req[22];
	g_last_peer_mac[1] = req[23];
	g_last_peer_mac[2] = req[24];
	g_last_peer_mac[3] = req[25];
	g_last_peer_mac[4] = req[26];
	g_last_peer_mac[5] = req[27];
	IP4_ADDR(&g_last_peer_ip, req[28], req[29], req[30], req[31]);
	g_last_peer_mac_valid = 1U;

	/* Ethernet header. */
	rep[0] = req[22];
	rep[1] = req[23];
	rep[2] = req[24];
	rep[3] = req[25];
	rep[4] = req[26];
	rep[5] = req[27];
	rep[6] = g_net_mac[0];
	rep[7] = g_net_mac[1];
	rep[8] = g_net_mac[2];
	rep[9] = g_net_mac[3];
	rep[10] = g_net_mac[4];
	rep[11] = g_net_mac[5];
	rep[12] = 0x08U;
	rep[13] = 0x06U;

	/* ARP reply payload. */
	rep[14] = 0x00U;
	rep[15] = 0x01U;
	rep[16] = 0x08U;
	rep[17] = 0x00U;
	rep[18] = 0x06U;
	rep[19] = 0x04U;
	rep[20] = 0x00U;
	rep[21] = 0x02U;
	rep[22] = g_net_mac[0];
	rep[23] = g_net_mac[1];
	rep[24] = g_net_mac[2];
	rep[25] = g_net_mac[3];
	rep[26] = g_net_mac[4];
	rep[27] = g_net_mac[5];
	rep[28] = (u8)ip4_addr1_val(*local_ip);
	rep[29] = (u8)ip4_addr2_val(*local_ip);
	rep[30] = (u8)ip4_addr3_val(*local_ip);
	rep[31] = (u8)ip4_addr4_val(*local_ip);
	rep[32] = req[22];
	rep[33] = req[23];
	rep[34] = req[24];
	rep[35] = req[25];
	rep[36] = req[26];
	rep[37] = req[27];
	rep[38] = req[28];
	rep[39] = req[29];
	rep[40] = req[30];
	rep[41] = req[31];
	(void)net_send_l2_frame(rep, NET_ARP_FRAME_LEN);
}

static void net_cache_peer_from_frame(struct pbuf *p, struct netif *inp)
{
	u8 hdr[NET_ETH_HDR_LEN + NET_IPV4_HDR_LEN];
	u16 copied;
	const ip4_addr_t *local_ip;

	if ((p == (struct pbuf *)0) || (inp == (struct netif *)0)) {
		return;
	}
	copied = pbuf_copy_partial(p, hdr, sizeof(hdr), 0U);
	if (copied != (u16)sizeof(hdr)) {
		return;
	}
	if ((hdr[12] != 0x08U) || (hdr[13] != 0x00U)) {
		return;
	}
	if ((hdr[14] >> 4U) != 4U) {
		return;
	}
	local_ip = netif_ip4_addr(inp);
	if ((hdr[30] != (u8)ip4_addr1_val(*local_ip)) ||
		(hdr[31] != (u8)ip4_addr2_val(*local_ip)) ||
		(hdr[32] != (u8)ip4_addr3_val(*local_ip)) ||
		(hdr[33] != (u8)ip4_addr4_val(*local_ip))) {
		return;
	}

	g_last_peer_mac[0] = hdr[6];
	g_last_peer_mac[1] = hdr[7];
	g_last_peer_mac[2] = hdr[8];
	g_last_peer_mac[3] = hdr[9];
	g_last_peer_mac[4] = hdr[10];
	g_last_peer_mac[5] = hdr[11];
	IP4_ADDR(&g_last_peer_ip, hdr[26], hdr[27], hdr[28], hdr[29]);
	g_last_peer_mac_valid = 1U;
}

static err_t netif_input_snoop(struct pbuf *p, struct netif *inp)
{
	net_try_reply_arp_request(p, inp);
	net_cache_peer_from_frame(p, inp);
	return ethernet_input(p, inp);
}

static err_t udp_send_payload_l2_fallback(
	const ip_addr_t *addr,
	u16_t port,
	const u8 *data,
	u16_t len
)
{
	const ip4_addr_t *src4;
	const ip4_addr_t *dst4;
	err_t e;
	u16_t ip_total_len;
	u16_t udp_total_len;
	u16_t frame_len;
	u8 *f;
	u16 src_port = NET_UDP_PORT;

	if ((addr == (const ip_addr_t *)0) || (data == (const u8 *)0) || !IP_IS_V4(addr)) {
		return ERR_ARG;
	}
	if ((len == 0U) || (len > NET_FALLBACK_MAX_UDP_PAYLOAD)) {
		return ERR_VAL;
	}

	if ((g_udp_pcb != (struct udp_pcb *)0) && (g_udp_pcb->local_port != 0U)) {
		src_port = (u16)g_udp_pcb->local_port;
	}
	src4 = netif_ip4_addr(&g_netif);
	dst4 = ip_2_ip4(addr);

	ip_total_len = (u16)(NET_IPV4_HDR_LEN + NET_UDP_HDR_LEN + len);
	udp_total_len = (u16)(NET_UDP_HDR_LEN + len);
	frame_len = (u16)(NET_ETH_HDR_LEN + ip_total_len);

	f = g_net_l2_frame;
	if ((g_last_peer_mac_valid != 0U) && ip4_addr_cmp(dst4, &g_last_peer_ip)) {
		f[0] = g_last_peer_mac[0];
		f[1] = g_last_peer_mac[1];
		f[2] = g_last_peer_mac[2];
		f[3] = g_last_peer_mac[3];
		f[4] = g_last_peer_mac[4];
		f[5] = g_last_peer_mac[5];
	} else {
		f[0] = 0xFFU;
		f[1] = 0xFFU;
		f[2] = 0xFFU;
		f[3] = 0xFFU;
		f[4] = 0xFFU;
		f[5] = 0xFFU;
	}
	f[6] = g_net_mac[0];
	f[7] = g_net_mac[1];
	f[8] = g_net_mac[2];
	f[9] = g_net_mac[3];
	f[10] = g_net_mac[4];
	f[11] = g_net_mac[5];
	f[12] = 0x08U;
	f[13] = 0x00U;

	f[14] = 0x45U;
	f[15] = 0x00U;
	write_be16(&f[16], ip_total_len);
	write_be16(&f[18], g_ipv4_tx_id++);
	write_be16(&f[20], 0x4000U);
	f[22] = 64U;
	f[23] = 17U;
	f[24] = 0U;
	f[25] = 0U;
	f[26] = (u8)ip4_addr1_val(*src4);
	f[27] = (u8)ip4_addr2_val(*src4);
	f[28] = (u8)ip4_addr3_val(*src4);
	f[29] = (u8)ip4_addr4_val(*src4);
	f[30] = (u8)ip4_addr1_val(*dst4);
	f[31] = (u8)ip4_addr2_val(*dst4);
	f[32] = (u8)ip4_addr3_val(*dst4);
	f[33] = (u8)ip4_addr4_val(*dst4);
	write_be16(&f[24], ipv4_hdr_checksum_20(&f[14]));

	write_be16(&f[34], src_port);
	write_be16(&f[36], port);
	write_be16(&f[38], udp_total_len);
	f[40] = 0U;
	f[41] = 0U;
	memcpy(&f[42], data, len);

	e = net_send_l2_frame(f, frame_len);
	return e;
}

static s32 process_request_packet(
	const u8 *req_buf,
	u32 req_len,
	u8 *resp_buf,
	u32 resp_cap,
	u32 *resp_len
)
{
	s32 rc;

	io_set_buffer_mode(req_buf, req_len, resp_buf, resp_cap);
	rc = process_request_once();
	*resp_len = g_io_tx_len;
	io_set_uart_mode();
	return rc;
}
#endif

#if ENABLE_LWIP_UDP
static err_t udp_send_payload(
	const ip_addr_t *addr,
	u16_t port,
	const u8 *data,
	u16_t len
)
{
	struct pbuf *pb;
	err_t e;
	err_t pe;

	if ((addr == (const ip_addr_t *)0) || (data == (const u8 *)0) || !IP_IS_V4(addr)) {
		return ERR_ARG;
	}
	if (len > NET_MAX_PACKET_BYTES) {
		return ERR_VAL;
	}

	/* Let lwIP build IP/UDP headers and resolve ARP for robust TX behavior. */
	pb = pbuf_alloc(PBUF_TRANSPORT, len, PBUF_RAM);
	if (pb == (struct pbuf *)0) {
		return ERR_MEM;
	}
	pe = pbuf_take(pb, data, len);
	if (pe != ERR_OK) {
		pbuf_free(pb);
		return pe;
	}

	e = udp_sendto(g_udp_pcb, pb, addr, port);
	pbuf_free(pb);
	return e;
}

static void udp_rx_cb(
	void *arg,
	struct udp_pcb *pcb,
	struct pbuf *p,
	const ip_addr_t *addr,
	u16_t port
)
{
	u32 resp_len = 0U;
	s32 rc = 0;
	err_t txe = ERR_OK;
	err_t txfb = ERR_OK;
	err_t arpe = ERR_OK;
	u32 rx_len = 0U;
	s32 arp_idx = -1;
	u32 tx_sent = 0U;
	struct eth_addr *arp_eth = (struct eth_addr *)0;
	const ip4_addr_t *arp_ip = (const ip4_addr_t *)0;
	(void)arg;
	(void)pcb;

	if (p == (struct pbuf *)0) {
		return;
	}
	rx_len = (u32)p->tot_len;
	if (rx_len > NET_MAX_PACKET_BYTES) {
		pbuf_free(p);
		return;
	}
	if (pbuf_copy_partial(p, g_net_rx_buf, p->tot_len, 0) != p->tot_len) {
		pbuf_free(p);
		return;
	}
	++g_udp_rx_pkts;

	rc = process_request_packet(g_net_rx_buf, rx_len, g_net_tx_buf, NET_MAX_PACKET_BYTES, &resp_len);
	if (rc == 0) {
		/* Force an ARP probe for host so MAC can be learned without host-side hacks. */
			arpe = etharp_request(&g_netif, ip_2_ip4(addr));
			arp_idx = etharp_find_addr(&g_netif, ip_2_ip4(addr), &arp_eth, &arp_ip);
			if ((resp_len > 0U) && (resp_len <= 65535U)) {
				txe = udp_send_payload(addr, port, g_net_tx_buf, (u16_t)resp_len);
				if ((txe == ERR_OK) && (arp_idx >= 0)) {
					tx_sent = 1U;
				}
				if (tx_sent == 0U) {
					txfb = udp_send_payload_l2_fallback(addr, port, g_net_tx_buf, (u16_t)resp_len);
					if (txfb == ERR_OK) {
						tx_sent = 1U;
						++g_udp_tx_fallback_ok;
					} else {
						++g_udp_tx_fallback_err;
					}
				}
				if (tx_sent != 0U) {
					++g_udp_tx_ok;
				} else {
					++g_udp_tx_err;
					g_udp_last_err = (s32)((txfb != ERR_OK) ? txfb : txe);
				}
			} else {
				txe = ERR_VAL;
				++g_udp_tx_err;
				g_udp_last_err = (s32)txe;
		}
	}
#if NET_DEBUG_LOG
	{
		u32 gem_txcnt = XEmacPs_ReadReg(XPAR_XEMACPS_0_BASEADDR, XEMACPS_TXCNT_OFFSET);
		u32 gem_tx1024 = XEmacPs_ReadReg(XPAR_XEMACPS_0_BASEADDR, XEMACPS_TX1024CNT_OFFSET);
		u32 gem_txu = XEmacPs_ReadReg(XPAR_XEMACPS_0_BASEADDR, XEMACPS_TXURUNCNT_OFFSET);
		u32 gem_rxcnt = XEmacPs_ReadReg(XPAR_XEMACPS_0_BASEADDR, XEMACPS_RXCNT_OFFSET);
		u32 gem_rxor = XEmacPs_ReadReg(XPAR_XEMACPS_0_BASEADDR, XEMACPS_RXORCNT_OFFSET);
		xil_printf(
			"UDP RX from=%d.%d.%d.%d:%d len=%d rc=%d arpe=%d tx_len=%d txe=%d txfb=%d txsent=%d uf=%d of=%d rx=%d tx_ok=%d tx_err=%d fb_ok=%d fb_err=%d last=%d lport=%d arp=%d dmac=%x:%x:%x:%x:%x:%x gem_tx=%d tx1024=%d txu=%d gem_rx=%d rxor=%d\r\n",
			(int)ip4_addr1_val(*ip_2_ip4(addr)),
			(int)ip4_addr2_val(*ip_2_ip4(addr)),
			(int)ip4_addr3_val(*ip_2_ip4(addr)),
		(int)ip4_addr4_val(*ip_2_ip4(addr)),
		(int)port,
		(int)rx_len,
		(int)rc,
			(int)arpe,
			(int)resp_len,
			(int)txe,
			(int)txfb,
			(int)tx_sent,
			(int)g_io_rx_underflow,
			(int)g_io_tx_overflow,
			(int)g_udp_rx_pkts,
			(int)g_udp_tx_ok,
			(int)g_udp_tx_err,
			(int)g_udp_tx_fallback_ok,
			(int)g_udp_tx_fallback_err,
			(int)g_udp_last_err,
			(int)g_udp_pcb->local_port,
			(int)arp_idx,
		(int)((arp_eth != (const struct eth_addr *)0) ? arp_eth->addr[0] : 0U),
		(int)((arp_eth != (const struct eth_addr *)0) ? arp_eth->addr[1] : 0U),
		(int)((arp_eth != (const struct eth_addr *)0) ? arp_eth->addr[2] : 0U),
		(int)((arp_eth != (const struct eth_addr *)0) ? arp_eth->addr[3] : 0U),
		(int)((arp_eth != (const struct eth_addr *)0) ? arp_eth->addr[4] : 0U),
		(int)((arp_eth != (const struct eth_addr *)0) ? arp_eth->addr[5] : 0U),
		(int)gem_txcnt,
		(int)gem_tx1024,
		(int)gem_txu,
		(int)gem_rxcnt,
		(int)gem_rxor
	);
	}
#endif

	pbuf_free(p);
}

static s32 net_init_udp(void)
{
	ip4_addr_t ipaddr;
	ip4_addr_t netmask;
	ip4_addr_t gw;

	lwip_init();

	IP4_ADDR(&ipaddr, NET_IP_ADDR0, NET_IP_ADDR1, NET_IP_ADDR2, NET_IP_ADDR3);
	IP4_ADDR(&netmask, NET_NETMASK0, NET_NETMASK1, NET_NETMASK2, NET_NETMASK3);
	IP4_ADDR(&gw, NET_GW_ADDR0, NET_GW_ADDR1, NET_GW_ADDR2, NET_GW_ADDR3);

	if (xemac_add(
		&g_netif,
		(ip_addr_t *)&ipaddr,
		(ip_addr_t *)&netmask,
		(ip_addr_t *)&gw,
		(unsigned char *)g_net_mac,
		XPAR_XEMACPS_0_BASEADDR
	) == (struct netif *)0) {
		return -40;
	}
	g_netif.input = netif_input_snoop;

	netif_set_default(&g_netif);
	netif_set_up(&g_netif);
	netif_set_link_up(&g_netif);
	net_force_emac_runtime_config();
	net_force_phy_profile();
	(void)etharp_gratuitous(&g_netif);

	g_udp_pcb = udp_new_ip_type(IPADDR_TYPE_V4);
	if (g_udp_pcb == (struct udp_pcb *)0) {
		return -41;
	}
	if (udp_bind(g_udp_pcb, IP_ADDR_ANY, NET_UDP_PORT) != ERR_OK) {
		udp_remove(g_udp_pcb);
		g_udp_pcb = (struct udp_pcb *)0;
		return -42;
	}
	udp_recv(g_udp_pcb, udp_rx_cb, (void *)0);

	xil_printf(
		"ETH UDP ready ip=%u.%u.%u.%u port=%u mac=%02x:%02x:%02x:%02x:%02x:%02x netif_up=%u link_up=%u\r\n",
		NET_IP_ADDR0, NET_IP_ADDR1, NET_IP_ADDR2, NET_IP_ADDR3, NET_UDP_PORT,
		NET_MAC0, NET_MAC1, NET_MAC2, NET_MAC3, NET_MAC4, NET_MAC5,
		(unsigned)netif_is_up(&g_netif),
		(unsigned)netif_is_link_up(&g_netif)
	);
	return 0;
}
#endif

int main(void)
{
	io_set_uart_mode();
	xil_printf("FW build %s\r\n", FW_BUILD_ID);

#if (FW_TRANSPORT_MODE == FW_TRANSPORT_LWIP_UDP)
	{
		net_platform_setup_interrupts();
		s32 rc = net_init_udp();
		if (rc != 0) {
			xil_printf("net_init_udp failed rc=%d\r\n", (int)rc);
			while (1) {
			}
		}
	}
	net_platform_enable_interrupts();
	xil_printf("ETH IRQs enabled\r\n");
	while (1) {
		s32 rx_pkts = (s32)xemacif_input(&g_netif);
#if NET_DEBUG_LOG
		static u32 rx_debug_total = 0U;
			if (rx_pkts > 0) {
				rx_debug_total += (u32)rx_pkts;
				if (rx_debug_total <= 16U) {
					xil_printf("ETH RX pkts=%d total=%d\r\n", (int)rx_pkts, (int)rx_debug_total);
				}
			}
#endif
#if defined(LWIP_TIMERS) && (LWIP_TIMERS != 0)
		sys_check_timeouts();
#endif
	}
#else
	while (1) {
		(void)process_request_once();
	}
#endif
}
