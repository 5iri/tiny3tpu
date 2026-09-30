#!/usr/bin/env python3
"""Rank completed boot/DDR/DMA/branch diagnostics without accepting physical timing."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ('baseline', 'build-ddr-seeds-uart-reset-guided-graph/seed-8', 'build-ddr-uart-reset-guided8-timing-sensitivity'),
    ('boot-first', 'build-ddr-boot-first-route/seed-8', 'build-ddr-boot-first-timing'),
    ('terminal', 'build-ddr-boot-first-terminal-route/seed-8', 'build-ddr-boot-first-terminal-timing'),
    ('fifo8', 'build-ddr-boot-first-fifo-route/seed-8', 'build-ddr-boot-first-fifo-timing'),
    ('fifo4', 'build-ddr-boot-first-fifo-seed4/seed-4', 'build-ddr-boot-first-fifo4-timing'),
    ('availability', 'build-ddr-boot-first-availability-route/seed-8', 'build-ddr-boot-first-availability-timing'),
    ('advance', 'build-ddr-boot-first-advance-route/seed-8', 'build-ddr-boot-first-advance-timing'),
    ('dma-only', 'build-ddr-dma-advance-only-route/seed-8', 'build-ddr-dma-advance-only-timing'),
    ('baseline-all-placement', 'build-ddr-uart-reset-all-placement/seed-8', 'build-ddr-uart-reset-all-placement-timing'),
    ('advance-all-placement', 'build-ddr-boot-first-advance-all-placement/seed-8', 'build-ddr-boot-first-advance-all-placement-timing'),
    ('branch4', 'build-ddr-boot-first-branch-route/seed-4', 'build-ddr-boot-first-branch4-timing'),
    ('branch6', 'build-ddr-boot-first-branch-seed6/seed-6', 'build-ddr-boot-first-branch6-timing'),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    assert not args.out.exists()
    hashes = {str(Path(__file__).resolve()): digest(__file__)}
    checked = {}

    def check(path):
        data = json.loads(path.read_text())
        hashes[str(path)] = digest(path)
        for key in ('sha256', 'output_sha256'):
            for name, expected in data.get(key, {}).items():
                if name not in checked:
                    checked[name] = digest(name)
                assert checked[name] == expected, (str(path), name)
        return data

    records = []
    for label, route_name, model_name in CASES:
        route = ROOT/route_name; model = ROOT/model_name
        routed = check(route/'manifest.json'); modeled = check(model/'manifest.json')
        assert routed['inputs_unchanged'] and routed['timing']['completed']
        assert routed['timing']['exit_code'] == 0 and routed['graph_analysis_completed']
        assert routed['no_combinational_loop_warning']
        assert not routed['full_soc_timing_accepted']
        assert modeled['sha256'][str(route/'manifest.json')] == digest(route/'manifest.json')
        values = []
        for v in modeled['variants']:
            p = model/f"graph-pcout-{v['symbolic_pcout_ns']}-carry-{v['symbolic_carry_arc_ns']}.tsv"
            assert digest(p) == v['graph_sha256']
            values.append(max(m['arrival_ns'] for m in v['maxima']))
        assert len(values) == 3
        records.append(dict(label=label, route=str(route), model=str(model),
            expanded_probes_ns=values, worst_probe_ns=max(values),
            native_diagnostic_mhz={k:v['mhz'] for k,v in routed['timing']['final_clocks'].items()},
            full_soc_timing_accepted=False))
    rejected = ROOT/'build-ddr-boot-first-branch-route/seed-8'
    bad = check(rejected/'manifest.json')
    assert not bad['timing']['completed'] and not bad['optimization_run_accepted']
    assert 'post-placement validity check failed' in (rejected/'route.log').read_text()
    hashes[str(rejected/'route.log')] = digest(rejected/'route.log')
    for name in ['build-ddr-boot-first-advance/iteration-integrity.json',
                 'build-ddr-boot-first-branch/iteration-integrity4.json']:
        audit = check(ROOT/name)
        assert audit['passed'] and not audit['full_soc_timing_accepted']
    best = min(records, key=lambda r:r['worst_probe_ns'])
    output = dict(passed=True,
        scope='Completed route/model artifact integrity and symbolic ranking only. Not physical timing closure. Detailed proof/functional audits cover the combined advance and branch candidates.',
        selection_metric='minimum worst interval across the same three symbolic PCOUT/carry probes; first retained route wins ties',
        selected=best['label'], selected_route=best['route'],
        completed_routes=records,
        rejected_routes=[dict(route=str(rejected), reason='Post-placement legality failure; no timing result')],
        unique_recorded_hashes_checked=len(checked), full_soc_timing_accepted=False,
        sha256=hashes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(dict(passed=True,selected=best['label'],worst_probe_ns=best['worst_probe_ns'],
                         completed_routes=len(records),rejected_routes=1,full_soc_timing_accepted=False)))


if __name__ == '__main__':
    main()
