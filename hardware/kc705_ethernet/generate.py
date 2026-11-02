#!/usr/bin/env python3
"""Generate the pinned LiteEth ARP/IPv4/UDP datapath and KC705 GMII interface."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

from migen import ClockDomain, ClockSignal, FSM, If, Instance, Mux, NextState, NextValue, ResetSignal, Signal
from migen.genlib.resetsync import AsyncResetSynchronizer
from litex.gen import LiteXModule
from litex.build.io import DDROutput
from litex.build.xilinx import XilinxPlatform
from liteeth.common import eth_phy_description, stream
from liteeth.core import LiteEthUDPIPCore
from liteeth.mac.padding import LiteEthMACPaddingInserter
from litex.soc.interconnect.packet import PacketFIFO


class GMII(LiteXModule):
    """125 MHz TX clock independent of the PHY-recovered RX clock; RX_ER is retained."""
    dw = 8
    tx_clk_freq = 125e6
    rx_clk_freq = 125e6

    def __init__(self, io, simulation):
        self.sink = sink = stream.Endpoint(eth_phy_description(8))
        self.source = source = stream.Endpoint(eth_phy_description(8))
        self.cd_eth_tx = ClockDomain('eth_tx')
        self.cd_eth_rx = ClockDomain('eth_rx')
        self.comb += self.cd_eth_tx.clk.eq(io['eth_tx_clk'])
        if simulation:
            self.comb += [self.cd_eth_rx.clk.eq(io['gmii_rx_clk']),
                          self.cd_eth_tx.rst.eq(ResetSignal()), self.cd_eth_rx.rst.eq(ResetSignal()),
                          io['gmii_gtx_clk'].eq(ClockSignal('eth_tx'))]
        else:
            self.specials += [Instance('BUFG', i_I=io['gmii_rx_clk'], o_O=self.cd_eth_rx.clk),
                             AsyncResetSynchronizer(self.cd_eth_tx, ResetSignal()),
                             AsyncResetSynchronizer(self.cd_eth_rx, ResetSignal()),
                             DDROutput(1, 0, io['gmii_gtx_clk'], ClockSignal('eth_tx'))]
        self.comb += sink.ready.eq(1)
        self.sync.eth_tx += [io['gmii_tx_en'].eq(sink.valid), io['gmii_tx_data'].eq(sink.data),
                             io['gmii_tx_er'].eq(sink.valid & sink.error)]
        delayed_dv = Signal()
        self.sync.eth_rx += [delayed_dv.eq(io['gmii_rx_dv']), source.valid.eq(io['gmii_rx_dv']),
                             source.data.eq(io['gmii_rx_data']), source.error.eq(io['gmii_rx_er'])]
        self.comb += source.last.eq(~io['gmii_rx_dv'] & delayed_dv)


class FixedPaddingInserter(LiteXModule):
    """LiteEth 2024.12 32-bit minimum-frame padding with final-word counter reset.

    Based on LiteEth mac/padding.py (EnjoyDigital, BSD-2-Clause). Upstream's
    partial final word at byte60 extends last_be but forgets to reset its counter,
    causing the following short frame to be emitted below the Ethernet minimum.
    """
    def __init__(self):
        self.sink = sink = stream.Endpoint(eth_phy_description(32))
        self.source = source = stream.Endpoint(eth_phy_description(32))
        counter = Signal(16)
        self.fsm = fsm = FSM(reset_state='COPY')
        mask = Signal(32)
        self.comb += mask.eq(Mux(sink.last_be == 1, 0xff,
                                Mux(sink.last_be == 2, 0xffff,
                                    Mux(sink.last_be == 4, 0xffffff, 0xffffffff))))
        fsm.act('COPY', sink.connect(source),
            If(sink.last, source.data.eq(sink.data & mask)),
            If(source.valid & source.ready,
                NextValue(counter, counter + 1),
                If(sink.last,
                    If(counter < 14, source.last.eq(0), source.last_be.eq(0), NextState('PAD')).Else(
                        If(counter == 14, source.last_be.eq(8)), NextValue(counter, 0)))))
        fsm.act('PAD', source.valid.eq(1), source.data.eq(0),
            If(counter >= 14, source.last.eq(1), source.last_be.eq(8)),
            If(source.ready, NextValue(counter, counter + 1),
                If(counter >= 14, NextValue(counter, 0), NextState('COPY'))))


class VerifiedFrameBuffer(LiteXModule):
    """Store a complete MAC frame before exposing its header or payload to IP/ARP.

    CRC errors arrive at the end of a frame, sometimes after UDP payload padding.
    Delaying only the UDP final beat would allow malformed short packets through.
    """
    def __init__(self):
        description = eth_phy_description(32)
        self.sink = sink = stream.Endpoint(description)
        self.source = source = stream.Endpoint(description)
        layout = stream.EndpointDescription(payload_layout=description.payload_layout,
                                            param_layout=[('bad_frame', 1)])
        self.fifo = fifo = PacketFIFO(layout, payload_depth=512, param_depth=4, buffered=True)
        bad = Signal()
        count = Signal(9)
        discard = Signal()
        limit = Signal()
        self.comb += [limit.eq(count == 511), sink.ready.eq(discard | fifo.sink.ready),
                      fifo.sink.valid.eq(sink.valid & ~discard),
                      fifo.sink.data.eq(sink.data), fifo.sink.error.eq(sink.error),
                      fifo.sink.last_be.eq(sink.last_be), fifo.sink.last.eq(sink.last | limit),
                      fifo.sink.bad_frame.eq(bad | (sink.error != 0) | limit),
                      fifo.source.connect(source, omit={'valid', 'ready', 'bad_frame'}),
                      source.valid.eq(fifo.source.valid & ~fifo.source.bad_frame),
                      fifo.source.ready.eq(source.ready | fifo.source.bad_frame)]
        self.sync += If(sink.valid & sink.ready,
            If(sink.last, bad.eq(0), count.eq(0), discard.eq(0)).Else(
                bad.eq(bad | (sink.error != 0)), count.eq(count + 1),
                If(limit, discard.eq(1))))


class UDPDatapath(LiteXModule):
    def __init__(self, udp_port, simulation):
        widths = {'sys_clk': 1, 'sys_rst': 1, 'eth_tx_clk': 1, 'gmii_rx_clk': 1,
                  'gmii_rx_dv': 1, 'gmii_rx_er': 1, 'gmii_rx_data': 8,
                  'gmii_gtx_clk': 1, 'gmii_tx_en': 1, 'gmii_tx_er': 1, 'gmii_tx_data': 8,
                  'local_mac_address': 48, 'local_ip_address': 32,
                  'crc_errors': 32, 'preamble_errors': 32}
        layout = {'valid': 1, 'ready': 1, 'data': 32, 'last': 1, 'last_be': 4, 'error': 4,
                  'src_port': 16, 'dst_port': 16, 'ip_address': 32, 'length': 16}
        for prefix in ('tx', 'rx'):
            widths.update({prefix + '_' + name: width for name, width in layout.items()})
        self.io = io = {name: Signal(width, name=name) for name, width in widths.items()}
        self.cd_sys = ClockDomain('sys')
        self.comb += [self.cd_sys.clk.eq(io['sys_clk']), self.cd_sys.rst.eq(io['sys_rst'])]
        self.phy = phy = GMII(io, simulation)
        self.core = core = LiteEthUDPIPCore(phy, io['local_mac_address'], io['local_ip_address'],
            clk_freq=100e6, dw=32, arp_entries=2, with_icmp=True, icmp_fifo_depth=512,
            with_sys_datapath=True, tx_cdc_depth=512, rx_cdc_depth=512,
            tx_cdc_buffered=True, rx_cdc_buffered=True, endianness='little')
        self.padding = FixedPaddingInserter()
        pipeline = core.mac.core.tx_datapath.pipeline
        for index, element in enumerate(pipeline):
            if isinstance(element, LiteEthMACPaddingInserter):
                pipeline[index] = self.padding
        self.frame_filter = VerifiedFrameBuffer()
        core.mac.core.rx_datapath.pipeline.insert(-1, self.frame_filter)
        port = core.udp.crossbar.get_port(udp_port, dw=32)
        for name in layout:
            if name == 'last_be':
                self.comb += [port.sink.last_be.eq(io['tx_last_be']),
                    io['rx_last_be'].eq(0),
                    If(port.source.last, io['rx_last_be'].eq(1 << ((port.source.length - 1) & 3)))]
            elif name == 'ready':
                self.comb += [io['tx_ready'].eq(port.sink.ready), port.source.ready.eq(io['rx_ready'])]
            else:
                self.comb += [getattr(port.sink, name).eq(io['tx_' + name]),
                              io['rx_' + name].eq(getattr(port.source, name))]
        self.comb += [io['crc_errors'].eq(core.mac.core.rx_datapath.crc_errors.status),
                      io['preamble_errors'].eq(core.mac.core.rx_datapath.preamble_errors.status)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--udp-port', type=int, default=9001)
    parser.add_argument('--simulation', action='store_true', help='Replace only FPGA clock/reset/output-clock primitives with RTL wiring')
    args = parser.parse_args()
    if not 1 <= args.udp_port <= 65535:
        parser.error('UDP port must be between 1 and 65535')
    versions = {name: importlib.metadata.version(name) for name in ('liteeth', 'litex', 'migen')}
    if versions != {'liteeth': '2024.12', 'litex': '2024.12', 'migen': '0.9.2'}:
        parser.error('Requires liteeth==2024.12, litex==2024.12, migen==0.9.2; got ' + str(versions))
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    platform = XilinxPlatform('xc7k325tffg900-2', [])
    design = UDPDatapath(args.udp_port, args.simulation)
    generated = platform.get_verilog(design, ios=set(design.io.values()), name='kc705_liteeth_udp')
    target = out / 'kc705_liteeth_udp.v'
    generated.write(str(target))
    manifest = {'versions': versions, 'udp_port': args.udp_port, 'system_clock_hz': 100000000,
                'gmii_tx_clock_hz': 125000000, 'gmii_rx_clock_hz': 125000000,
                'data_width': 32, 'last_be': 'one-hot final valid byte: 1,2,4,8',
                'payload_byte_order': 'data[7:0] is the first byte', 'simulation_primitives': args.simulation,
                'receive_commit': 'Complete MAC frames buffered; CRC/RX_ER/oversize frames discarded before ARP/IP/UDP',
                'hardware_protocols': ['Ethernet MAC CRC', 'ARP', 'IPv4', 'ICMP', 'UDP'],
                'udp_checksum': 'Transmit zero; LiteEth 2024.12 does not validate RX UDP checksum. MAC CRC remains enabled.',
                'physical_validation': False,
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    (out / 'liteeth-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
