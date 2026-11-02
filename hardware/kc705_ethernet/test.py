#!/usr/bin/env python3
"""Run the PHY management and actual LiteEth GMII protocol/CDC regressions."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--test', choices=('all', 'mdio', 'gmii'), default='all')
    parser.add_argument('--generator-python', default=sys.executable,
                        help='Python with liteeth2024.12/litex2024.12/migen0.9.2')
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    def run(command, name):
        command = list(map(str, command))
        (out / (name + '-command.json')).write_text(json.dumps(command, indent=2) + '\n')
        with (out / (name + '.log')).open('w') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out / (name + '.log')).read_text()[-6000:])
        return (out / (name + '.log')).read_text()
    report = {'passed': True, 'scope': 'RTL simulation only; no physical PHY, routing, cable or host network timing', 'tests': {}}
    if args.test in ('all', 'mdio'):
        run(['iverilog', '-g2012', '-s', 'test_mdio', '-o', out / 'mdio.vvp',
             HERE / 'test_mdio.sv', HERE / 'kc705_phy_mdio.sv'], 'mdio-build')
        log = run(['vvp', out / 'mdio.vvp'], 'mdio-run')
        if 'PASS MDIO:' not in log:
            raise RuntimeError('MDIO test did not complete')
        report['tests']['mdio'] = {'passed': True, 'checks': 'PHY address, gigabit-only advertisements, turnaround release, BMSR double-read, link loss, no PHY response, recovery, reset'}
    if args.test in ('all', 'gmii'):
        run([args.generator_python, HERE / 'generate.py', '--out', out, '--simulation'], 'generate')
        run(['verilator', '--binary', '--timing', '-j', '2', '-Wno-fatal', '--top-module', 'test_gmii',
             '--Mdir', out / 'obj', HERE / 'test_gmii.sv', out / 'kc705_liteeth_udp.v'], 'gmii-build')
        log = run([out / 'obj/Vtest_gmii'], 'gmii-run')
        count = sum(line.startswith('PASS UDP payload=') for line in log.splitlines())
        if count != 8 or 'PASS actual LiteEth:' not in log:
            raise RuntimeError('GMII test did not complete all packets')
        report['tests']['gmii'] = {'passed': True, 'valid_udp_packets': count, 'rejected_packets': 4,
            'checks': 'Hardware ARP; byte order; lengths1/2/3/4/17/1400/1472; one-hot tail byte; RX backpressure; Ethernet minimum padding; bad CRC/RX_ER/wrong UDP port/oversized frame rejection; recovery',
            'system_clock_hz': 100000000, 'gmii_clock_hz': 125000000,
            'generated_rtl_sha256': hashlib.sha256((out / 'kc705_liteeth_udp.v').read_bytes()).hexdigest()}
    report['source_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in HERE.iterdir() if path.suffix in ('.py', '.sv')}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
