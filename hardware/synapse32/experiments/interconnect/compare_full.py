#!/usr/bin/env python3
"""Read-only checks of candidate top ports, memory INITs, clocks and DDR cells."""
import argparse
from collections import Counter
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('baseline', type=Path)
parser.add_argument('candidate', type=Path)
args = parser.parse_args()
gold, gate = [json.loads(p.read_text())['modules']['kc705_synapse32_top']
              for p in (args.baseline, args.candidate)]
# Top-level bit IDs also match for this isolated candidate; this intentionally
# strict assertion should be reviewed before applying to unrelated changes.
assert gold['ports'] == gate['ports'], 'top-level ports changed'


def ram_params(module):
    return {name: cell['parameters'] for name, cell in module['cells'].items()
            if cell['type'] == 'RAMB36E1'}


assert ram_params(gold) == ram_params(gate), 'boot RAM parameters/INIT changed'
for kind in ('PLLE2_ADV', 'BUFG', 'BUFGCE', 'IDELAYCTRL', 'IDELAYE2',
             'ODELAYE2', 'ISERDESE2', 'OSERDESE2', 'IOBUF', 'IOBUFDS'):
    params = [sorted(json.dumps(cell['parameters'], sort_keys=True)
                     for cell in module['cells'].values() if cell['type'] == kind)
              for module in (gold, gate)]
    assert params[0] == params[1], kind + ' parameters changed'
print('PASS: top ports, boot RAM parameters/INIT, clock and DDR primitive parameters')
for name, module in (('baseline', gold), ('candidate', gate)):
    counts = Counter(cell['type'] for cell in module['cells'].values())
    print(name, json.dumps(dict(sorted(counts.items()))))
