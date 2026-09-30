#!/usr/bin/env python3
"""Read-only audit of the frozen combined synthesis and state parameters."""
import argparse
from collections import Counter
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('out', type=Path)
args = parser.parse_args()
out = args.out.absolute()
root = Path(__file__).resolve().parents[4]
manifest = json.loads((out / 'manifest.json').read_text())
original_script = (root / 'build-ddr/synth.ys').read_text()
expected = original_script
for source, overlay in manifest['substitutions'].items():
    assert expected.count(source) == 1
    expected = expected.replace(source, overlay)
expected = expected.replace(str(root / 'build-ddr/soc.json'), str(out / 'soc.json'))
assert expected == (out / 'synth.ys').read_text()
assert '/synapse32/rtl/core_modules/divider.v' in expected
assert '/rejected/' not in expected
print('PASS: exactly two RTL path substitutions plus output path; original divider')

gold_soc = (root / 'hardware/synapse32/synapse32_dram_soc.sv').read_text()
gate_soc = (out / 'synapse32_dram_soc.sv').read_text()
start = '    wire boot_address'
end = '    wire uart_address'
def without_decode(source):
    return source[:source.index(start)] + source[source.index(end):]
assert without_decode(gold_soc) == without_decode(gate_soc)
print('PASS: SoC changes confined to boot decode; module parameters, RAM init, and transaction logic unchanged')

gold, gate = [json.loads(p.read_text())['modules']['kc705_synapse32_top']
              for p in (root / 'build-ddr/soc.json', out / 'soc.json')]
assert gold['ports'] == gate['ports']
kinds = sorted({c['type'] for c in gold['cells'].values()} -
               {'$scopeinfo', 'CARRY4', 'INV', 'MUXF7', 'MUXF8',
                'LUT1', 'LUT2', 'LUT3', 'LUT4', 'LUT5', 'LUT6'})
for kind in kinds:
    params = [Counter(json.dumps(c['parameters'], sort_keys=True)
                      for c in m['cells'].values() if c['type'] == kind)
              for m in (gold, gate)]
    assert params[0] == params[1], kind
    print(f'PASS: {kind} parameter/INIT multiset ({sum(params[0].values())} cells)')
for kind in ('RAMB36E1', 'RAM32M'):
    params = [{n: c['parameters'] for n, c in m['cells'].items() if c['type'] == kind}
              for m in (gold, gate)]
    assert params[0] == params[1], kind + ' named memories'
    print(f'PASS: {kind} parameters/INIT also identical by instance name')
for label, m in [('baseline', gold), ('combined', gate)]:
    counts = Counter(c['type'] for c in m['cells'].values())
    print(label, 'LUT1..6', sum(counts[f'LUT{i}'] for i in range(1, 7)),
          'CARRY4', counts['CARRY4'], 'MUXF7', counts['MUXF7'], 'MUXF8', counts['MUXF8'])
print('Compositional evidence only: parameter equality is not a whole-netlist equivalence proof.')
