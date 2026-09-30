#!/usr/bin/env python3
"""Fail closed on incomplete KC705 timing; expose actual missing-path witnesses.

This consumes hash-verified routed and expanded graphs. It adds no timing
exceptions or delay estimates and does not modify the backend or hardware.
Exit 0 requires complete validated timing; exit 2 means timing is not accepted.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from synapse32_analyze_timing_graph import analyze
from synapse32_audit_timing_coverage import audit as port_audit
from synapse32_missing_cell_arcs import audit as carry_audit

REQUIRED_VALIDATIONS = ('kintex_carry_and_cascade_delays', 'generic_ff_lut_mux_delays',
                        'clock_skew_and_hold', 'reset_recovery_removal', 'ddr_phy_io_timing')

def decide(*, missing_carry_arcs, ignored_dynamic_ports, unknown_delays,
           validation, intervals, unresolved_nodes):
    reasons = []
    if missing_carry_arcs:
        reasons.append(f'Native graph omits {missing_carry_arcs} required carry dependencies')
    if ignored_dynamic_ports:
        reasons.append(f'Native graph leaves {ignored_dynamic_ports} connected dynamic ports unclassified')
    if unknown_delays:
        reasons.append('Expanded graph still uses symbolic, unvalidated primitive delays')
    for name in sorted(set(REQUIRED_VALIDATIONS) | set(validation)):
        if validation.get(name) is not True:
            reasons.append('Not validated: ' + name)
    if unresolved_nodes:
        reasons.append('Timing graph contains unresolved nodes')
    if not intervals:
        reasons.append('No checked timing intervals')
    for item in intervals:
        delay, budget = item['delay_ns'], item['budget_ns']
        if budget is None:
            reasons.append('No verified budget for ' + item['domain'])
        elif not math.isfinite(delay) or not math.isfinite(budget) or budget <= 0 or delay > budget:
            reasons.append(f"Expanded diagnostic exceeds budget: {item['domain']} ({delay} ns / {budget} ns)")
    return dict(accepted=not reasons, reasons=list(dict.fromkeys(reasons)))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def actual_native_graph(route, manifest):
    # Guided runs also save a normalized graph with symbolic optimizer arcs
    # removed for apples-to-apples offline comparison. That is not the graph
    # that produced their native Fmax headline.
    name = 'guidance-timing-graph.tsv' if manifest.get('carry_guidance_normalized') else 'timing-graph.tsv'
    path = route / name
    if str(path) not in manifest['output_sha256']:
        raise ValueError('Actual native graph is not recorded: ' + str(path))
    return path


def budget(row):
    # Only relationships explicitly evidenced by the current KC705 contract.
    s, d = row['source_clock'], row['sink_clock']
    if s in ('clk', 'soc.cpu_clk') and d in ('clk', 'soc.cpu_clk'):
        period = 10.0
    elif s == d and s in ('clk200', 'memory.iodelay_clk'):
        period = 5.0
    else:
        return None
    return period if row['source_edge'] == row['sink_edge'] else period / 2


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--route', type=Path, required=True)
    p.add_argument('--sensitivity', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    route, sensitivity, out = a.route.resolve(), a.sensitivity.resolve(), a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    checked = {}

    def read(path):
        data = json.loads(path.read_text())
        for key in ('sha256', 'output_sha256'):
            for name, expected in data.get(key, {}).items():
                if digest(name) != expected:
                    raise ValueError('Stale input: ' + name)
                checked[name] = expected
        checked[str(path)] = digest(path)
        return data

    r = read(route / 'manifest.json')
    model = read(sensitivity / 'manifest.json')
    assert r['inputs_unchanged'] and r['timing']['completed'] and r['graph_analysis_completed']
    assert model['model_application_completed']
    assert model['sha256'][str(route / 'manifest.json')] == digest(route / 'manifest.json')
    native_path = actual_native_graph(route, r)
    routed = route / 'routed.json'
    for path in (native_path, routed):
        assert r['output_sha256'][str(path)] == digest(path)
    native_analysis = analyze(native_path)
    assert not native_analysis['unresolved_nodes']
    for clock, entry in r['timing']['final_clocks'].items():
        maxima = [v['arrival_ns'] for v in native_analysis['maxima']
                  if v['source_clock'] == v['sink_clock'] == clock and v['source_edge'] == v['sink_edge']]
        assert maxima and abs(max(maxima) - 1000 / entry['mhz']) < 0.002, clock
    native_rows = [line.rstrip('\n').split('\t') for line in native_path.open()]
    cells = next(iter(json.loads(routed.read_text())['modules'].values()))['cells']
    carry = carry_audit(native_rows, cells)
    ports = port_audit(native_path, routed)
    (out / 'native-carry-coverage.json').write_text(json.dumps(carry, indent=2) + '\n')
    (out / 'native-port-coverage.json').write_text(json.dumps(ports, indent=2) + '\n')
    native_cell_arcs = {(v[1], v[2], v[3]) for v in native_rows if v[0] == 'CELLARC'}
    native_clock_ports = {(v[1], v[2]) for v in native_rows if v[0] == 'CLOCK'}
    port_names = {(v[1], v[3]): v[7] for v in native_rows if v[0] == 'PORT'}
    native_types = {(v[1], v[3]): int(v[5]) for v in native_rows if v[0] == 'PORT'}
    witnesses, intervals, repair_checks = [], [], []
    # Keep memory bounded: consume one existing probe graph at a time.
    del native_rows
    for variant in model['variants']:
        pc, ca = variant['symbolic_pcout_ns'], variant['symbolic_carry_arc_ns']
        path = sensitivity / f'graph-pcout-{pc}-carry-{ca}.tsv'
        assert digest(path) == variant['graph_sha256']
        checked[str(path)] = variant['graph_sha256']
        maximum = max(variant['maxima'], key=lambda v: v['arrival_ns'])
        result = analyze(path, tracked_cells={maximum['cell']})
        assert not result['unresolved_nodes']
        actual = {(v['source_clock'], v['source_edge'], v['sink_clock'], v['sink_edge']): v['arrival_ns'] for v in result['maxima']}
        for expected in variant['maxima']:
            key = tuple(expected[k] for k in ('source_clock', 'source_edge', 'sink_clock', 'sink_edge'))
            assert abs(actual[key] - expected['arrival_ns']) < 1e-6
            intervals.append(dict(probe=dict(pcout_ns=pc, carry_arc_ns=ca),
                                  domain=f'{key[0]}[{key[1]}] -> {key[2]}[{key[3]}]',
                                  delay_ns=expected['arrival_ns'], budget_ns=budget(expected)))
        traced = [v for v in result['tracked_maxima'] if v['group'] == 'tracked_input'
                  and v['source_clock'] == maximum['source_clock']
                  and v['sink_clock'] == maximum['sink_clock']
                  and v['source_edge'] == maximum['source_edge']
                  and v['sink_edge'] == maximum['sink_edge']]
        assert len(traced) == 1 and abs(traced[0]['arrival_ns'] - maximum['arrival_ns']) < 1e-6
        trace = traced[0]
        enriched, gaps = [], []
        for step in trace['path']:
            entry = dict(step, primitive=cells[step['cell']]['attributes'].get('X_ORIG_TYPE', cells[step['cell']]['type']),
                         net=port_names.get((step['cell'], step['port'])))
            enriched.append(entry)
        for left, right in zip(enriched, enriched[1:]):
            if left['cell'] == right['cell'] and (left['cell'], left['port'], right['port']) not in native_cell_arcs:
                gaps.append(dict(cell=left['cell'], primitive=left['primitive'], input=left['port'], output=right['port'],
                                 substituted_delay_ns=round(right['arrival_ns'] - left['arrival_ns'], 6)))
        launch = enriched[0]
        capture = enriched[-1]
        trace.update(path=enriched, missing_native_cell_arcs=gaps,
                     native_launch_class=native_types[launch['cell'], launch['port']],
                     native_launch_clock_arc_present=(launch['cell'], launch['port']) in native_clock_ports,
                     native_capture_class=native_types[capture['cell'], capture['port']],
                     native_capture_clock_arc_present=(capture['cell'], capture['port']) in native_clock_ports,
                     probe=dict(pcout_ns=pc, carry_arc_ns=ca), budget_ns=budget(maximum),
                     scope='Diagnostic under recorded model assumptions; not physical delay or Fmax.')
        witnesses.append(trace)
        if pc == 0 and ca == 0:
            rows = [line.rstrip('\n').split('\t') for line in path.open()]
            restored = carry_audit(rows, cells)
            assert restored['carry_arcs_complete']
            repair_checks.append(dict(expanded_graph=str(path), required_carry_arcs=restored['required_carry_arcs'],
                                      missing_carry_arcs=restored['missing_carry_arc_count'], connectivity_complete=True,
                                      delay_validation_complete=False))
            del rows
        print(f'Checked probe PCOUT={pc}, carry={ca}: {maximum["arrival_ns"]:.3f} ns; '
              f'{len(gaps)} internal connections on the worst path absent from native graph', flush=True)

    validation = dict(kintex_carry_and_cascade_delays=False, generic_ff_lut_mux_delays=False,
                      clock_skew_and_hold=False, reset_recovery_removal=False, ddr_phy_io_timing=False)
    decision = decide(missing_carry_arcs=carry['missing_carry_arc_count'],
                      ignored_dynamic_ports=len(ports['ignored_dynamic_ports']), unknown_delays=True,
                      validation=validation, intervals=intervals, unresolved_nodes=False)
    record = dict(scope='Full-SoC timing acceptance check; native Fmax is informational only. Expanded intervals retain all recorded symbolic assumptions.',
                  **decision, native_fmax=r['timing']['final_clocks'],
                  actual_native_graph=str(native_path), native_fmax_reproduced=True,
                  native_carry_costs_symbolic=bool(r.get('carry_guidance_normalized')),
                  normalized_comparison_graph=str(route / 'timing-graph.tsv'),
                  native_missing_carry_arcs=carry['missing_carry_arc_count'],
                  native_carry_cells_affected=carry['carry_cells_with_missing_arcs'],
                  native_ignored_ports_by_type={k:dict(cells=v['cell_count'], ports=v['port_count']) for k,v in ports['ignored_dynamic_by_type'].items()},
                  expanded_carry_connectivity=repair_checks, validation=validation,
                  intervals=intervals, witnesses=witnesses, full_soc_timing_accepted=decision['accepted'],
                  sha256=checked)
    for name in ('synapse32_check_soc_timing.py', 'synapse32_analyze_timing_graph.py',
                 'synapse32_missing_cell_arcs.py', 'synapse32_audit_timing_coverage.py'):
        source = Path(__file__).with_name(name)
        record['sha256'][str(source)] = digest(source)
    (out / 'report.json').write_text(json.dumps(record, indent=2) + '\n')
    print('ACCEPTED' if decision['accepted'] else 'NOT ACCEPTED: incomplete/unvalidated timing; see ' + str(out / 'report.json'))
    return 0 if decision['accepted'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
