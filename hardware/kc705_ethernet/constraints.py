#!/usr/bin/env python3
"""KC705 GMII pin map and explicit, unqualified external-timing review constraints."""
import argparse
import json
from pathlib import Path

PINS = {
    'gmii_rx_clk': 'U27', 'gmii_gtx_clk': 'K30', 'gmii_rx_dv': 'R28', 'gmii_rx_er': 'V26',
    'gmii_tx_en': 'M27', 'gmii_tx_er': 'N29', 'phy_rst_n': 'L20', 'phy_mdc': 'R23', 'phy_mdio': 'J21',
}
for index, pin in enumerate('U30 U25 T25 U28 R19 T27 T26 T28'.split()):
    PINS['gmii_rx_data[%d]' % index] = pin
for index, pin in enumerate('N27 N25 M29 L28 J26 K26 L30 J28'.split()):
    PINS['gmii_tx_data[%d]' % index] = pin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    lines = ['# AMD UG810 v1.9 Table 1-18 / LiteX-Boards xilinx_kc705.py.',
             '# This file sets pins and input-clock frequency; it does not qualify GMII IO or CDC timing.']
    for port, pin in PINS.items():
        lines += ['set_property PACKAGE_PIN %s [get_ports {%s}]' % (pin, port),
                  'set_property IOSTANDARD LVCMOS25 [get_ports {%s}]' % port]
    lines += ['create_clock -name gmii_rx_clk -period 8.000 [get_ports gmii_rx_clk]']
    (out / 'gmii-pins.xdc').write_text('\n'.join(lines) + '\n')
    (out / 'gmii-timing-review.xdc').write_text('''# REVIEW ONLY. Do not silently discard these commands or claim timing closure.
# Marvell 88E1111 Rev M Tables140/141: TXsetup2ns, TXhold0ns; RXsetup2.5ns, RXhold0.5ns.
# Values below include an ASSUMED +/-0.2ns PCB clock/data skew; actual KC705 routing must be checked.
# RX data arrival range relative to previous RX clock: min0.3ns, max5.7ns.
set_input_delay -clock [get_clocks gmii_rx_clk] -max 5.700 [get_ports {gmii_rx_data[*] gmii_rx_dv gmii_rx_er}]
set_input_delay -clock [get_clocks gmii_rx_clk] -min 0.300 [get_ports {gmii_rx_data[*] gmii_rx_dv gmii_rx_er}]
# GTX output clock must be traced through the ODDR to the 125MHz PLL output before defining gmii_gtx_clk.
# set_output_delay -clock [get_clocks gmii_gtx_clk] -max 2.200 [get_ports {gmii_tx_data[*] gmii_tx_en gmii_tx_er}]
# set_output_delay -clock [get_clocks gmii_gtx_clk] -min -0.200 [get_ports {gmii_tx_data[*] gmii_tx_en gmii_tx_er}]
# Also required: MDIO timing, asynchronous FIFO Gray-bus max-delay/skew and reset recovery/removal.
# A blanket asynchronous-clock false-path is insufficient to qualify Gray-pointer crossings.
''')
    manifest = {'physical_timing_qualified': False, 'route_allowed': False,
                'phy': 'Marvell 88E1111, GMII, Clause22 address7; 1000BASE-T full duplex only',
                'clocks_hz': {'sys': 100000000, 'eth_tx': 125000000, 'eth_rx': 125000000},
                'pins': PINS, 'phy_reset_ms': 10,
                'references': ['https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content',
                 'https://www.marvell.com/content/dam/marvell/en/public-collateral/transceivers/marvell-phys-transceivers-alaska-88e1111-datasheet.pdf'],
                'remaining': ['Verify PCB clock/data skew', 'Qualify external GMII/MDIO setup and hold',
                              'Constrain and inspect asynchronous FIFO CDC', 'Run physical link/error/packet tests']}
    (out / 'gmii-constraints-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
