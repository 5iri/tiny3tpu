#!/usr/bin/env python3
"""Audit connected timing ports from an exact live routed-graph replay.

This is a structural coverage audit, not validation of delay values or STA.
Unknown/ignored dynamic ports remain explicit; no exception list grants signoff.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

CLASSES = ['clock_input', 'generated_clock', 'register_input', 'register_output',
           'comb_input', 'comb_output', 'startpoint', 'endpoint', 'ignore']


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def audit(graph, routed):
    cells = next(iter(json.loads(routed.read_text())['modules'].values()))['cells']
    ports, incoming, fanout = {}, {}, Counter()
    records = Counter()
    with graph.open() as f:
        assert next(f).rstrip() == 'VERSION\t1'
        for line in f:
            v = line.rstrip('\n').split('\t'); records[v[0]] += 1
            if v[0] == 'PORT':
                _, cell, kind, port, direction, cls, count, net = v
                assert cells[cell]['type'] == kind
                assert (cell, port) not in ports
                ports[cell, port] = dict(cell=cell, type=kind, port=port,
                    direction=direction, timing_class=CLASSES[int(cls)],
                    clock_count=int(count), net=net)
            elif v[0] == 'NETARC':
                _, net, source, sp, sink, dp, delay = v
                assert (sink, dp) not in incoming
                incoming[sink, dp] = (source, sp)
                fanout[source, sp] += 1
    expected = {(n, p) for n, c in cells.items() for p, bits in c['connections'].items() if bits}
    assert set(ports) == expected, 'Live export does not cover every connected routed port'
    ignored = []
    for key, p in ports.items():
        if p['timing_class'] != 'ignore':
            continue
        if p['direction'] == 'input':
            driver = incoming.get(key)
            # Constants do not carry dynamic timing paths. Undriven pins are
            # retained as unknown instead of silently discarded.
            if driver and cells[driver[0]]['type'] in ('PSEUDO_GND', 'PSEUDO_VCC'):
                continue
            ignored.append(dict(p, driver=list(driver) if driver else None))
        elif p['direction'] == 'output' and fanout[key]:
            if p['type'] not in ('PSEUDO_GND', 'PSEUDO_VCC'):
                ignored.append(dict(p, fanout=fanout[key]))
        elif p['direction'] == 'inout':
            ignored.append(p)
    by_type = defaultdict(lambda: {'cells': set(), 'ports': Counter()})
    for p in ignored:
        by_type[p['type']]['cells'].add(p['cell'])
        by_type[p['type']]['ports'][p['port']] += 1
    groups = {k: {'cell_count': len(v['cells']), 'cells': sorted(v['cells']),
                  'port_count': sum(v['ports'].values()), 'ports': dict(sorted(v['ports'].items()))}
              for k, v in sorted(by_type.items())}
    return {'scope': 'Structural connected-port coverage only; delay bounds, clock topology, setup/hold and hardware signoff are not validated.',
            'records': dict(records), 'cell_types': dict(Counter(c['type'] for c in cells.values())),
            'ignored_dynamic_by_type': groups,
            'ignored_dynamic_ports': sorted(ignored, key=lambda p: (p['type'], p['cell'], p['port'])),
            'all_dynamic_ports_classified': not ignored,
            'full_soc_timing_accepted': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay', type=Path, required=True)
    a = p.parse_args(); root = a.replay.resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    assert manifest['passed'] and manifest['routed_json_exact'] and manifest['fmax_reproduced']
    graph, routed = root/'timing-graph.tsv', root/'routed.json'
    assert digest(graph) == manifest['graph_sha256']
    parent = json.loads(Path(manifest['parent']).read_text())
    old = Path(parent['command'][parent['command'].index('--write')+1])
    assert json.loads(old.read_text()) == json.loads(routed.read_text())
    result = audit(graph, routed)
    result['sha256'] = {str(q): digest(q) for q in [graph, routed, root/'manifest.json', Path(__file__).resolve()]}
    (root/'coverage.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'ignored_dynamic_by_type': {k: {'cells':v['cell_count'], 'ports':v['port_count']}
                    for k,v in result['ignored_dynamic_by_type'].items()},
                    'full_soc_timing_accepted': False}, indent=2))


if __name__ == '__main__':
    main()
