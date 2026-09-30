#!/usr/bin/env python3
"""Verify retained physical resources and timing coverage after incremental routing."""
import argparse
import copy
from synapse32_ddr_decode_equivalence import CONE, TARGET, verify_packed_logic
import hashlib
import json
from collections import Counter
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--route', type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
route = a.route.resolve()
digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
checked = {}


def read(path):
    data = json.loads(path.read_text())
    for key in ('sha256', 'output_sha256'):
        for name, value in data.get(key, {}).items():
            assert digest(name) == value, (str(path), name)
    checked[str(path)] = digest(path)
    return data


r = read(route / 'manifest.json')
assert r['inputs_unchanged'] and r['timing']['completed']
assert r['placement_unchanged'] and r['clock_targets_restored']
assert r['no_combinational_loop_warning'] and r['graph_analysis_completed']
preserved = read(route / 'preserved-routes.json')
parent_path = root / 'build-routing-import-unique-control-mid2-v3'
parent = read(parent_path / 'manifest.json')
assert parent['passed']
before = json.loads((parent_path / 'routed.json').read_text())['modules']['top']
after = json.loads((route / 'routed.json').read_text())['modules']['top']


def resources(module, name):
    parts = module['netnames'][name]['attributes']['ROUTING'].split(';')
    assert len(parts) % 3 == 0
    # Binding strength may intentionally increase; real wires and pips may not.
    return sorted((parts[i], parts[i + 1]) for i in range(0, len(parts), 3))


route_changes = [n for n in preserved['nets'] if resources(before, n) != resources(after, n)]
kept = set(preserved['nets'])
copies = {x['copy'] for x in r['reset_replication']['replicas']}
assert r['ddr_decode_composition']['target']==TARGET
subdesigns=[]
for module in [before,after]:
    subset=copy.deepcopy(module)
    subset['cells']={n:subset['cells'][n] for n in CONE}
    subdesigns.append({'modules':{'top':subset}})
assert verify_packed_logic(*subdesigns)
composition_proved=True
copies.add(TARGET)  # This sole cell's changed function/wiring is exhaustively checked above.



def graph(path, module):
    constant_bits=set()
    for kind, value in [('GND',0),('VCC',1)]:
        driver=module['cells']['$PACKER_'+kind+'_DRV']
        assert driver['type']=='PSEUDO_'+kind
        assert driver['port_directions']['Y']=='output'
        assert driver['connections']['Y']==module['netnames']['$PACKER_'+kind+'_NET']['bits']
        constant_bits.update(driver['connections']['Y'])
    def constant_input(cell, pin):
        c=module['cells'][cell]
        assert c['port_directions'][pin]=='input'
        return all(b in constant_bits or b in ('0','1') for b in c['connections'][pin])
    pins, clock_arcs, cells, nets = Counter(), Counter(), Counter(), {}
    with path.open() as f:
        for line in f:
            v = line.rstrip('\n').split('\t')
            if v[0] == 'PORT' and v[1] not in copies:
                # Preserve type, direction and timing class/clock count per cell.
                if not (v[4]=='input' and v[5]=='4' and constant_input(v[1],v[3])):
                    pins[(v[1], v[2], *v[4:7])] += 1
            elif v[0] == 'CLOCK' and v[1] not in copies:
                clock_arcs[tuple(v)] += 1
            elif v[0] == 'CELLARC' and v[1] not in copies:
                if not constant_input(v[1],v[2]):
                    cells[(v[1], v[-1])] += 1
            elif v[0] == 'NETARC' and v[1] in kept:
                key = tuple(v[1:6])
                assert key not in nets
                nets[key] = v[6]
    return pins, clock_arcs, cells, nets


old = graph(parent_path / 'timing-graph.tsv', before)
new = graph(route / 'timing-graph.tsv', after)
coverage = dict(ddr_decode_composition_proved=composition_proved, existing_variable_and_output_timing_classes_exact=old[0] == new[0],
                existing_clock_arcs_exact=old[1] == new[1],
                existing_variable_input_cell_arc_counts_and_delays_exact=old[2] == new[2])
net_changes = [key for key in old[3].keys() | new[3].keys() if old[3].get(key) != new[3].get(key)]
result = dict(scope='Physical resource and existing timing-coverage integrity only; native timing remains incomplete. Pin legalization may add/remove constant-input RAM annotations: only combinational inputs and arcs sourced by verified PSEUDO_GND/VCC nets or literal constants are excluded from variable-input comparisons. All clock and output classifications remain checked.',
              route=str(route), preserved_nets=len(kept), locked=preserved['locked'],
              changed_preserved_routes=route_changes, changed_preserved_netarcs=len(net_changes),
              preserved_netarc_count=len(old[3]), coverage=coverage,
              native_partial_clocks=r['timing']['final_clocks'],
              full_soc_timing_accepted=False, sha256=checked,
              script_sha256=digest(__file__))
result['passed'] = all(coverage.values()) and (not preserved['locked'] or (not route_changes and not net_changes))
(route / 'incremental-decode-integrity-v2.json').write_text(json.dumps(result, indent=2) + '\n')
assert result['passed'], result
print('PASS coverage integrity;', len(route_changes), 'changed retained routes;', len(net_changes), 'changed retained net arcs')
