# KC705 hardware Ethernet transport

This implementation adds a Gigabit GMII MAC, ARP, IPv4, ICMP and UDP in hardware,
using pinned LiteEth 2024.12. The existing VexRiscv/TPU executes the applications;
the CPU exchanges complete UDP packets with two on-chip packet buffers. There is
no CPU network stack and no DDR dependency. UART firmware remains supported.

The **100 microsecond target is demonstrated for a simulated transport exchange**.
It is not the time to compute a fresh model result, and it is not a physical
host-to-board measurement.

## Measured latency

The full test connects two actual LiteEth stacks through digital GMII. One node
contains the production VexRiscv/TPU firmware and packet peripheral; the other
models the host network endpoint. System clocks are 100 MHz, Ethernet clocks
125 MHz, and simulation resolution 1 ns. Every inference output word and the
replayed response bytes are checked.

| Exchange | Simulated round trip |
| --- | ---: |
| Initial ownership query, including ARP | 16.03 us |
| Warm 16-byte echo | 8.11 us |
| Warm 1,268-byte echo | 90.00 us |
| Fresh banana, raw result | 4.15010 ms |
| Fresh banana, compact result | 5.31476 ms |

The raw banana request includes 3.81332 ms of compute. Its 2,480-byte application
response occupies two Ethernet frames. UDP viewers therefore select raw results
by default: coordinate compression costs more CPU time than it saves on this
link. UART viewers retain compact coordinates. A freshly rebuilt UART image
measured 17.71686 ms for compact banana; the earlier throughput audit measured
18.83847 ms. These are separately linked firmware images and consecutive poses,
not identical machine instructions or physical USB measurements.

The Ethernet results exclude analog PHY latency, cable, switch, host NIC/driver,
OS scheduling and Python socket latency. ARP-cold and ARP-warm exchanges are
reported separately. Cached duplicate replies are validation of replay handling,
not fresh inference throughput. See [evidence.json](evidence.json).

## Hardware and build

The KC705 uses a Marvell 88E1111 PHY, strapped by default for GMII at MDIO address
7. The design advertises only 1000BASE-T full duplex; a gigabit peer is required.
GMII TX has an independent 125 MHz PLL clock, and RX uses the PHY clock. LiteEth
owns the clock-domain crossings. The management controller resets the PHY,
configures advertisement, and polls both BMSR reads needed for its latch-low link
bit. Pins and LVCMOS25 constraints match the official KC705 platform.

Defaults are board IPv4 **192.168.1.50**, MAC **02:00:00:00:70:51**, UDP **9001**.
The host needs a reachable address on that subnet, for example 192.168.1.100.
The software does not change host interface configuration. There is no DHCP.

Install the generator dependencies into the existing isolated LiteX environment:

```sh
.venv-ddr-compat/bin/python -m pip install -r hardware/kc705_ethernet/requirements.txt

# Existing exported application artifacts are required; no retraining.
.venv/bin/python sidequests/showcase/build_board.py \
  --out build-ethernet/showcase --io-transport udp
.venv/bin/python sidequests/showcase/build_classifier.py \
  --out build-ethernet/classifier --io-transport udp
.venv/bin/python sidequests/cloth/build_compiled_board.py --compile-only \
  --out build-ethernet/cloth --io-transport udp

# Fresh hardware synthesis; a UART image cannot acquire Ethernet by patching RAM.
.venv-ddr-compat/bin/python tools/kc705_open_build.py synth \
  --cpu vexriscv-lite --no-ddr --cordic --synapse32-dir ../synapse32 \
  --ethernet --firmware-source sidequests/showcase/firmware.c \
  --firmware-include build-ethernet/showcase --build-dir build-ethernet/board
```

Use `--ethernet-ip` and `--ethernet-mac` on the hardware builder to change the
static addresses. TPU transport is independent: select `--tpu-transport direct`
on both firmware and hardware builds to enable the native TPU register path.
The default remains the mailbox. Both I/O and TPU choices are checked against
the firmware manifest.

Full-design synthesis passes with 32 DSP48E1, 6 RAMB18E1 and 19 RAMB36E1 cells;
the loaded firmware hex is identical to the full GMII simulation image.
**Routing/export remain blocked by the Ethernet build
guard** until external GMII/MDIO setup and hold, PCB skew, and asynchronous FIFO
constraints are qualified. `constraints.py` emits pin assignments and a separate
timing review file; the latter contains explicit assumptions and incomplete
constraints. The current router's clock-frequency estimate cannot qualify these
interfaces. No Ethernet bitstream was flashed or physically tested.

## Reproduce the checks

```sh
# PHY management and actual MAC/ARP/IPv4/UDP/GMII tests.
.venv-ddr-compat/bin/python hardware/kc705_ethernet/test.py \
  --out build-ethernet/ip-tests

# Production application through CPU, packet buffers, both MACs and GMII.
.venv/bin/python tests/test_udp_soc.py --with-mac \
  --ethernet-python .venv-ddr-compat/bin/python \
  --board build-ethernet/showcase --out build-ethernet/showcase-full-mac

# Production classifier and cloth at the UDP stream boundary.
.venv/bin/python tests/test_udp_soc.py --demo classifier \
  --board build-ethernet/classifier --out build-ethernet/classifier-udp-soc
.venv/bin/python tests/test_udp_soc.py --demo cloth \
  --board build-ethernet/cloth --out build-ethernet/cloth-udp-soc

.venv/bin/python tests/test_udp_transport.py
```

Ordinary CMake tests include the packet peripheral, firmware adapters, host
transport and MDIO controller. To include the generated GMII test, configure
`-DTINY3TPU_ETHERNET_PYTHON=/absolute/path/to/.venv-ddr-compat/bin/python`.
Reports fingerprint firmware, generated RTL, fixtures and test sources.

After a separately qualified Ethernet image is programmed, the clients are:

```sh
# Viewer dependencies, in addition to the existing compiler/JAX environment.
.venv/bin/python -m pip install Pillow pyserial
.venv/bin/python sidequests/showcase/live.py \
  --udp 192.168.1.50:9001 --board build-ethernet/showcase
.venv/bin/python sidequests/showcase/classifier_live.py \
  --udp 192.168.1.50:9001 --board build-ethernet/classifier
.venv/bin/python sidequests/cloth/live.py --compiled --udp 192.168.1.50:9001

# Transport-only echo; no model execution. Reports latency percentiles.
.venv/bin/python sidequests/showcase/udp_transport.py \
  --udp 192.168.1.50:9001 --requests 100 --payload-bytes 1264
```

The echo benchmark adds the four-byte `ECQ1` prefix, making that application
message 1,268 bytes before the UDP envelope and network headers.

## Packet and session contract

Existing IFQ1/IFR1 and CLQ3/CLR3 application messages remain unchanged. Every UDP
payload starts with a 20-byte little-endian envelope:

| Field | Bytes | Meaning |
| --- | ---: | --- |
| Magic | 4 | `T3U1` |
| Transaction | 4 | Request ID, modulo 2^32 |
| Total | 4 | Complete application message size, at most 4096 |
| Offset | 4 | Chunk byte offset |
| Length | 4 | This chunk's payload size, at most 1400 |

Requests occupy one datagram. Responses use application chunks, keeping UDP
payloads at most 1420 bytes within a 1500-byte IP MTU. IP fragmentation and jumbo
frames are not required. The host accepts reordered and identical duplicate
chunks, rejects conflicting overlaps, verifies the inner protocol, and enforces
a finite deadline. It permits one outstanding request and never automatically
retries a stateful request after an ambiguous timeout.

`EHQ1` is a read-only ownership query. Its `EHR1` reply contains four uint32 words:
version (1), ownership (0 unclaimed, 1 same peer, 2 busy), last accepted application
transaction, and flags (bit 0 means that transaction is valid). The first valid
application request claims the peer IP/source port/destination port until firmware
reset. The host defaults to local UDP port 9002. Reconnecting the same peer queries
the last accepted ID and continues at the next ID; it does not retry an unknown
result after loss. Changing peer requires a firmware reset in this version.

An identical latest transaction replays the cached reply without running the
application. A changed body with that ID, an older ID, or another peer is rejected.
`EER1` errors contain code and detail: 1 busy, 2 stale (detail is the last ID),
3 conflicting body (detail is the last ID). Forward ID distances must be below
2^31. This suppression is scoped to the running firmware session, not persistence
across resets. Echo (`ECQ1` to `ECR1`) and ownership queries neither advance the
application nor replace its replay cache.

## CPU packet registers

The peripheral occupies `0x20004000–0x20005fff` only when `ENABLE_ETHERNET=1`.
Aligned 32-bit accesses use little-endian byte lanes. Payload BRAM is not reset;
validity state is reset, so stale memory is never published as a packet.

| Offset | Register |
| --- | --- |
| `0x00` | Status: RX valid bit 0, TX ready bit 1, dropped bit 2, bad frame bit 3 |
| `0x04`, `0x08`, `0x0c` | RX length, peer IPv4, ports (source low 16, destination high 16) |
| `0x10`, `0x14`, `0x18` | TX length, destination IPv4, ports (source low 16, destination high 16) |
| `0x1c` | Command: release RX bit 0, commit TX bit 1, clear counters bit 2 |
| `0x20`, `0x24`, `0x28` | Dropped count, invalid packet count, ABI version `0x00010000` |
| `0x400–0x9ff` | RX payload, held until release |
| `0x1000–0x15ff` | TX payload, writable while TX ready |

Maximum UDP payload is 1472 bytes. Oversized or malformed streams are discarded.
Incoming packets are dropped whole while the CPU owns the prior RX packet.
TX metadata and payload are frozen until the stack accepts the final beat.
The peripheral uses two RAMB18s and needs no DMA access to CPU memory.

## IP integration details and remaining work

The generator includes local fixes for three issues observed in the pinned
32-bit LiteEth path: minimum-frame padding counter reset, UDP tail-byte signaling
after Ethernet padding, and preventing late CRC errors from exposing an already
parsed request. A complete-frame buffer validates MAC frames before ARP/IP sees
them. Directed tests check all final-byte lanes, padded short frames, bad CRC,
RX_ER, wrong UDP port, oversized frames, recovery and backpressure. Installed
LiteEth package files are not modified. The adapted code's original notices are
in [LICENSE.liteeth](LICENSE.liteeth).

LiteEth 2024.12 transmits a zero UDP checksum and does **not** verify received UDP
checksums. Ethernet CRC checking is enabled. Adding UDP checksum validation,
qualifying physical timing, and testing host latency distributions remain work.
The CPU still copies result words into the packet buffer. Reaching 100 us for a
fresh banana result requires reducing its compute and serialization costs as
well as the link latency.

Primary references: [LiteEth](https://github.com/enjoy-digital/liteeth),
[AMD KC705 UG810](https://docs.amd.com/v/u/en-US/ug810_KC705_Eval_Bd),
[Marvell 88E1111](https://www.marvell.com/content/dam/marvell/en/public-collateral/transceivers/marvell-phys-transceivers-alaska-88e1111-datasheet.pdf).
