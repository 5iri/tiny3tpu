#!/usr/bin/env python3
"""Prove the exact changed UART decode for all 32-bit addresses and bases."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from prepare import OLD, NEW, patch

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--uart', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
out = a.out.resolve()
out.mkdir(parents=True, exist_ok=False)
source = a.uart.resolve()
reference = source.read_text()
candidate = patch(reference)
assert candidate.replace(NEW, OLD) == reference
(out / 'uart.v').write_text(candidate)
# Copy the actual replacement expressions. UART_BASE is unconstrained, so the
# proof includes fallback layouts, wraparound and all unaligned accesses.
gold = OLD.replace('uart_valid', 'gold').replace('`UART_BASE', 'base')
gate = NEW.replace('uart_valid', 'gate').replace('`UART_BASE', 'base')
harness = ('module equiv(input [31:0] addr, base, output same);\n'
           'wire gold, gate;\n' + gold + '\n' + gate + '\n'
           'assign same = gold == gate;\nendmodule\n')
(out / 'harness.v').write_text(harness)
script = out / 'proof.ys'
script.write_text(f'read_verilog {out / "harness.v"}\n'
                  'prep -top equiv; opt; check -assert; '
                  'sat -prove same 1 -verify;\n')
yosys = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
with (out / 'proof.log').open('w') as log:
    rc = subprocess.run([str(yosys), '-Q', '-T', '-s', str(script)],
                        stdout=log, stderr=subprocess.STDOUT).returncode
paths = [source, Path(__file__).resolve(), Path(__file__).with_name('prepare.py').resolve(),
         yosys, out / 'uart.v', out / 'harness.v', script]
record = dict(passed=rc == 0, reference=str(source),
              claim='Exact combinational decode equality for every 32-bit address and base. '
                    'No aligned-access or reachable-state assumption; every other RTL byte is unchanged.',
              sha256={str(q): hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out / 'results.json').write_text(json.dumps(record, indent=2) + '\n')
assert record['passed'], out / 'proof.log'
print('PASS UART decode for all 32-bit addresses and bases, including unaligned accesses')
