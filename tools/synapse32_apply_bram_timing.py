#!/usr/bin/env python3
"""Add a narrow DS182 boot-RAM setup/clock-to-output model to a verified graph.

Read-only timing experiment: no netlist, placement, routing or RTL mutation.
Unsupported RAM profiles and active undriven pins are errors. This adds neither
clock skew nor hold analysis and cannot establish whole-SoC timing closure.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from synapse32_analyze_timing_graph import analyze

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = 'https://docs.amd.com/v/u/en-US/ds182_Kintex_7_Data_Sheet'


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def number(params, key, default=0):
    value = params.get(key)
    return default if value is None else int(value, 2)


def limits_from_text(text):
    result = {}
    for key, marker, expected in [
            ('address', 'TRCCK_ADDRA/', .65),
            ('data', 'TRDCK_DI_WF_NC/', .78),
            ('enable', 'TRCCK_EN/TRCKC_EN', .48),
            ('write_enable', 'TRCCK_WEA/', .54),
            ('reset', 'TRCCK_RSTRAM/', .34)]:
        row = text[text.index(marker):].split('ns, Min', 1)[0]
        pairs = re.findall(r'([0-9]+\.[0-9]+)/\s*([0-9]+\.[0-9]+)', row)
        assert len(pairs) == 6, (key, pairs)
        setup, hold = zip(*[(float(s), float(h)) for s, h in pairs])
        assert max(setup) == expected, (key, setup)
        result[key] = dict(setup_ns=max(setup), hold_ns=max(hold),
                           setup_all_grades=setup, hold_all_grades=hold)
    row = text[text.index('Clock CLK to DOUT output\n(without output register)'):].split('ns, Max', 1)[0]
    values = [float(v) for v in re.findall(r'\d+\.\d+', row)]
    assert len(values) == 6 and max(values) == 2.44
    result['read_output'] = dict(clock_to_output_ns=max(values), all_grades=values)
    row = text[text.index('FMAX_BRAM_WF_NC Block RAM'):].split('MHz', 1)[0]
    values = [float(v) for v in re.findall(r'\d+\.\d+', row)]
    assert len(values) == 6 and min(values) == 372.44
    result['internal_fmax'] = dict(minimum_mhz=min(values), all_grades=values)
    return result


def check_profile(cell):
    p = cell['parameters']
    assert cell['type'] == 'RAMB36E1_RAMB36E1'
    for k, v in [('RAM_MODE', 'TDP'), ('WRITE_MODE_A', 'NO_CHANGE'),
                 ('RAM_EXTENSION_A', 'NONE'), ('RAM_EXTENSION_B', 'NONE'),
                 ('EN_ECC_READ', 'FALSE'), ('EN_ECC_WRITE', 'FALSE')]:
        default = 'FALSE' if k.startswith('EN_ECC') else None
        assert p.get(k, default) == v, (k, p.get(k))
    for k, v in [('READ_WIDTH_A', 2), ('WRITE_WIDTH_A', 2), ('READ_WIDTH_B', 0),
                 ('WRITE_WIDTH_B', 0), ('DOA_REG', 0), ('DOB_REG', 0),
                 ('IS_CLKARDCLK_INVERTED', 0)]:
        assert number(p, k) == v, (k, p.get(k))


def apply_model(lines, cells, limits):
    ports, incoming, fanout = {}, {}, Counter()
    for v in lines:
        if v[0] == 'PORT': ports[v[1], v[3]] = v
        elif v[0] == 'NETARC':
            incoming[v[4], v[5]] = (v[2], v[3]); fanout[v[2], v[3]] += 1
    rams = {n: c for n, c in cells.items() if c['type'] == 'RAMB36E1_RAMB36E1'}
    assert rams, 'No RAMB36E1 cells to model'
    replacements, clock_rows, decisions = {}, [], []

    def constant(key):
        driver = incoming.get(key)
        if driver is None: return None
        kind = cells[driver[0]]['type']
        return 0 if kind == 'PSEUDO_GND' else 1 if kind == 'PSEUDO_VCC' else None

    for name, cell in sorted(rams.items()):
        check_profile(cell)
        attrs, params = cell['attributes'], cell['parameters']
        mapped = {port: attrs.get('X_ORIG_PORT_' + port) for c, port in ports if c == name}
        # TDP packing creates otherwise unmapped high WEBWE pins tied low.
        for port, orig in list(mapped.items()):
            if orig is None:
                assert re.fullmatch(r'WEBWE[LU][4-7]', port), (name, port)
                assert constant((name, port)) == 0, (name, port)
                mapped[port] = 'WEBWE[' + port[-1] + ']'
        assert all(mapped.values()), name
        clk = ports[name, 'CLKARDCLKL'][-1]
        assert clk == ports[name, 'CLKARDCLKU'][-1]
        assert incoming.get((name, 'CLKARDCLKL')) is not None
        assert constant((name, 'CLKARDCLKL')) is None
        aliases = defaultdict(list)
        for port, orig in mapped.items(): aliases[orig].append(ports[name, port][-1])
        assert all(len(set(nets)) == 1 for nets in aliases.values()), 'Packed logical alias mismatch'
        for port, orig in mapped.items():
            key = (name, port); v = ports[key]; direction = v[4]
            base = orig.split('[')[0]
            cls, row, reason = None, None, None
            if base == 'CLKARDCLK': cls, reason = 0, 'active_A_clock'
            elif direction == 'output':
                if fanout[key]:
                    assert orig in ('DOADO[0]', 'DOADO[1]'), (name, orig)
                    cls, reason = 3, 'A_read_output_no_optional_register'
                    row = ['CLOCK', name, port, '0', 'CLKARDCLKL', '0', '0', '0', str(limits['read_output']['clock_to_output_ns'])]
                else: reason = 'unused_output'
            elif base in ('ADDRARDADDR', 'DIADI', 'DIPADIP', 'ENARDEN', 'WEA', 'RSTRAMARSTRAM'):
                assert key in incoming, ('Undriven active input', key)
                if base == 'RSTRAMARSTRAM':
                    value = constant(key)
                    # Packer may absorb constant inversion into the primitive.
                    assert value is not None
                    assert value ^ number(params, 'IS_RSTRAMARSTRAM_INVERTED') == 0
                group = {'ADDRARDADDR':'address', 'DIADI':'data', 'DIPADIP':'data',
                         'ENARDEN':'enable', 'WEA':'write_enable', 'RSTRAMARSTRAM':'reset'}[base]
                cls, reason = 2, group
                bound = limits[group]
                row = ['CLOCK', name, port, '0', 'CLKARDCLKL', '0', str(bound['setup_ns']), str(bound['hold_ns']), '0']
            else:
                # B is inactive (zero widths); optional output registers are
                # bypassed. Require no live source for inactive B input paths.
                inactive = base in ('ADDRBWRADDR', 'DIBDI', 'DIPBDIP', 'ENBWREN',
                    'WEBWE', 'CLKBWRCLK', 'RSTRAMB', 'REGCEB', 'RSTREGB',
                    'REGCEAREGCE', 'RSTREGARSTREG')
                assert inactive, ('Unsupported port', name, port, orig)
                assert key not in incoming or constant(key) is not None, ('Live inactive pin', key)
                reason = 'inactive_B_or_bypassed_output_register'
            if cls is not None:
                assert v[5:7] == ['8', '0'], ('Baseline RAM unexpectedly modeled', name, port)
                copy = list(v); copy[5:7] = [str(cls), '1' if row else '0']; replacements[key] = copy
                if row: clock_rows.append(row)
            decisions.append(dict(cell=name, port=port, logical_port=orig, reason=reason,
                                  timing_class=cls if cls is not None else 8,
                                  driven=key in incoming, constant=constant(key), fanout=fanout[key]))
    result = [replacements.get((v[1], v[3]), v) if v[0] == 'PORT' else v for v in lines]
    return result + clock_rows, decisions


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); replay = a.replay.resolve(); out = a.out.resolve()
    manifest = json.loads((replay/'manifest.json').read_text())
    graph, routed = replay/'timing-graph.tsv', replay/'routed.json'
    assert manifest['passed'] and manifest['routed_json_exact'] and manifest['fmax_reproduced']
    assert digest(graph) == manifest['graph_sha256']
    parent = json.loads(Path(manifest['parent']).read_text())
    original_routed = Path(parent['command'][parent['command'].index('--write') + 1])
    assert json.loads(original_routed.read_text()) == json.loads(routed.read_text())
    text_path = ROOT/'build-dsp-preg-timing/ds182.txt'; pdf = text_path.with_suffix('.pdf')
    proof = json.loads((text_path.parent/'limits.json').read_text())
    for q in (text_path, pdf): assert digest(q) == proof['sha256'][str(q)]
    limits = limits_from_text(text_path.read_text())
    cells = next(iter(json.loads(routed.read_text())['modules'].values()))['cells']
    lines = [line.rstrip('\n').split('\t') for line in graph.open()]
    enhanced, decisions = apply_model(lines, cells, limits)
    out.mkdir(parents=True, exist_ok=False)
    candidate = out/'timing-graph.tsv'; candidate.write_text(''.join('\t'.join(v)+'\n' for v in enhanced))
    result = analyze(candidate, tracked_cells={p['cell'] for p in decisions})
    record = dict(scope=__doc__, source=SOURCE_URL, document='AMD DS182 v2.19 Table 34, pp.38–40',
                  replay=str(replay), source_netlist_unchanged=True, routing_unchanged=True,
                  limits=limits, modeled_ram_count=len({p['cell'] for p in decisions}),
                  decisions=decisions, full_soc_timing_accepted=False,
                  passed=not result['unresolved_nodes'],
                  sha256={str(q):digest(q) for q in [graph, routed, replay/'manifest.json', text_path, pdf,
                          ROOT/'tools/synapse32_analyze_timing_graph.py', Path(__file__).resolve(), candidate]})
    (out/'manifest.json').write_text(json.dumps(record, indent=2)+'\n')
    (out/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed':record['passed'], 'modeled_ram_count':record['modeled_ram_count'],
                      'maxima':result['maxima'], 'full_soc_timing_accepted':False},indent=2))
    if not record['passed']: raise SystemExit('Expanded graph has unresolved nodes')


if __name__ == '__main__': main()
