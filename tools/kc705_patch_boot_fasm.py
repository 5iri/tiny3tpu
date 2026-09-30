#!/usr/bin/env python3
"""Patch only verified 16 x 16384x2 boot RAM INIT data in an existing FASM.

Specific to the retained KC705 Synapse32 layout. Fail closed if the original
firmware, routed parameters, or FASM bit mapping disagree. Never routes/flashes.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--routed-json', type=Path)
p.add_argument('--fasm', type=Path)
p.add_argument('--reference-hex', type=Path)
p.add_argument('--tilegrid', type=Path,
               default=Path('/tmp/tiny3tpu-kc705-frame-db/kintex7/xc7k325t/tilegrid.json'))
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
base = root / 'build-grade2-cpu-pe-ddr-capture-pair-x119y40-bit'
routed_path = a.routed_json or base / 'export-routed.json'
fasm_path = a.fasm or base / 'latest.fasm'
reference_hex = a.reference_hex or root / 'build-ddr-uart-prefix/board/firmware.hex'
route = json.loads(routed_path.read_text())
cells = next(iter(route['modules'].values()))['cells']
grid = json.loads(a.tilegrid.read_text())
sites = {s: t for t, v in grid.items() for s in v.get('sites', {})}
original = {}
address = 0
for token in reference_hex.read_text().split():
    if token.startswith('@'):
        address = int(token[1:], 16)
    else:
        original[address] = int(token, 16)
        address += 1
data = a.binary.read_bytes()
assert 0 < len(data) <= 65536
data += b'\0' * (-len(data) % 4)
words = [int.from_bytes(data[i:i+4], 'little') for i in range(0, len(data), 4)]
words += [0x00000013] * (16384 - len(words))  # unused boot space: NOP
lines = fasm_path.read_text().splitlines()
pattern = re.compile(r"(\S+\.RAMB18_Y[01]\.INIT_[0-9A-F]{2})\[255:0\] = 256'b([01]+)")
features = {m[1]: int(m[2], 2) for line in lines if (m := pattern.fullmatch(line))}
replacement = {}
reconstructed = [0] * 16384
for plane in range(16):
    cell = cells[f'soc.boot_mem.0.{plane}']
    assert cell['type'] == 'RAMB36E1_RAMB36E1'
    assert int(cell['parameters']['READ_WIDTH_A'], 2) == 2
    assert int(cell['parameters']['WRITE_WIDTH_A'], 2) == 2
    tile = sites[cell['attributes']['NEXTPNR_BEL'].split('/')[0]]
    old_bits = ''.join(cell['parameters'][f'INIT_{i:02X}'][::-1] for i in range(128))
    assert len(old_bits) == 32768
    for addr, word in original.items():
        assert int(old_bits[2*addr:2*addr+2][::-1], 2) == ((word >> (2*plane)) & 3), (plane, addr)
    for half in range(2):
        for chunk in range(64):
            key = f'{tile}.RAMB18_Y{half}.INIT_{chunk:02X}'
            old = sum((old_bits[2*(chunk*256+b)+half] == '1') << b for b in range(256))
            assert features[key] == old, key
            value = sum(((words[chunk*256+b] >> (2*plane+half)) & 1) << b for b in range(256))
            replacement[key] = value
            for b in range(256):
                reconstructed[chunk*256+b] |= ((value >> b) & 1) << (2*plane+half)
assert reconstructed == words
updated = []
changed = 0
for line in lines:
    m = pattern.fullmatch(line)
    if m and m[1] in replacement:
        new = f"{m[1]}[255:0] = 256'b{replacement[m[1]]:0256b}"
        changed += new != line
        updated.append(new)
    else:
        updated.append(line)
assert len(replacement) == 2048
assert [x for x in lines if not (m := pattern.fullmatch(x)) or m[1] not in replacement] == [x for x in updated if not (m := pattern.fullmatch(x)) or m[1] not in replacement]
a.out.mkdir(parents=True, exist_ok=True)
(a.out / 'firmware.hex').write_text('@00000000\n' + '\n'.join(f'{w:08x}' for w in words) + '\n')
(a.out / 'patched.fasm').write_text('\n'.join(updated) + '\n')
result = dict(passed=True, patched_init_features=changed, checked_original_words=len(original),
              full_64k_fasm_reconstruction_exact=True, all_non_boot_init_features_unchanged=True,
              route_unchanged=True, clock_unchanged=True,
              sha256={str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in
                      [a.binary, reference_hex, fasm_path, routed_path, a.out/'patched.fasm', Path(__file__)]})
(a.out / 'patch.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k:v for k,v in result.items() if k != 'sha256'}, indent=2))
