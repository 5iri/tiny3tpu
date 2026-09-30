#!/usr/bin/env python3
"""Recheck current UART/reset/arithmetic experiments and unchanged workloads."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
records = []


def check(path):
    path = ROOT / path
    data = json.loads(path.read_text())
    count = 0
    for key in ('sha256', 'output_sha256'):
        for name, value in data.get(key, {}).items():
            assert digest(name) == value, (str(path), name)
            count += 1
    records.append(dict(manifest=str(path), sha256=digest(path), checked_hashes=count))
    return data


proofs = []
for folder in ('build-uart-reset-control-proved', 'build-mul-carry-save-proved',
               'build-divider-sign-select-proved', 'build-uart-read-parallel-proved'):
    proof = check(Path(folder) / 'results.json')
    assert proof['passed']
    synth = check(Path(folder) / 'synthesis-comparison.json')
    assert synth['firmware_identical'] and synth['constraints_identical']
    proofs.append(folder)

functional = []
for kind in ('dma', 'gemm'):
    baseline = check(Path(f'build-ddr-{kind}-uart-local-burst-verified/system/results.json'))
    for name in ('uart-reset', 'uart-reset-csa', 'uart-reset-divsign',
                 'uart-read-divsign', 'parallel-chooser-revalidated'):
        data = check(Path(f'build-ddr-{kind}-{name}/system/results.json'))
        assert all(baseline[k] == data[k] for k in ('profile', 'metrics', 'dma'))
        functional.append(dict(kind=kind, candidate=name, all_profile_metrics_dma_exact=True,
                               cpu_ipc=data['profile']['instructions'] / data['profile']['cpu_edges'],
                               system_cycles=data['metrics']['system_cycles'],
                               memory_model=data['metrics']['memory_model'],
                               litedram_frontend_simulated=data['configuration']['litedram_frontend_simulated']))

routes = []
for prefix, analysis in [
    ('uart-reset-guided-graph', 'uart-reset-guided'),
    ('uart-reset-original-graph', 'uart-reset-original'),
    ('uart-reset-csa-guided-graph', 'uart-reset-csa-guided'),
    ('uart-reset-divsign-original-graph', 'uart-reset-divsign-original'),
    ('uart-read-divsign-original-graph', 'uart-read-divsign-original'),
    ('uart-read-divsign-replica-graph', 'uart-read-divsign-replica'),
]:
    for seed in (4, 8):
        path = Path(f'build-ddr-seeds-{prefix}/seed-{seed}')
        route = check(path / 'manifest.json')
        timing_path = Path(f'build-ddr-{analysis}{seed}-timing-sensitivity')
        timing = check(timing_path / 'manifest.json')
        assert route['inputs_unchanged'] and route['timing']['completed'] and route['graph_analysis_completed']
        assert 'combinational loop' not in (ROOT / path / 'route.log').read_text().lower()
        assert not timing['full_soc_timing_accepted'] and not timing['timing_audit_passed']
        for variant in timing['variants']:
            filename = f"graph-pcout-{variant['symbolic_pcout_ns']}-carry-{variant['symbolic_carry_arc_ns']}.tsv"
            assert digest(ROOT / timing_path / filename) == variant['graph_sha256']
        maxima = [round(max(x['arrival_ns'] for x in v['maxima']), 6) for v in timing['variants']]
        routes.append(dict(route=str(path), native_partial_clocks=route['timing']['final_clocks'],
                           symbolic_intervals_ns=maxima))

selected = min(routes, key=lambda r: max(r['symbolic_intervals_ns']))
assert selected['route'] == 'build-ddr-seeds-uart-reset-guided-graph/seed-8'
record = dict(passed=True,
              scope='Exact functional/artifact checks. Selected diagnostic minimizes the worst of three symbolic probes; it does not establish physical Fmax. Workloads use variable-latency memory, not LiteDRAM/PHY or hardware.',
              proofs=proofs, functional=functional, routes=routes, selected=selected['route'],
              full_soc_timing_accepted=False, checked_manifests=records, script_sha256=digest(__file__))
out = ROOT / 'build-uart-reset-control-proved/iteration-integrity.json'
out.write_text(json.dumps(record, indent=2) + '\n')
print('PASS', len(records), 'manifests;', len(routes), 'routes; exact smoke and 45-shape performance')
