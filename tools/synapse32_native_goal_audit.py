#!/usr/bin/env python3
"""Verify the native >100 MHz diagnostic target separately from physical signoff."""
import argparse
import hashlib
import json
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
integrity = read(route / 'incremental-decode-integrity-v4.json')
assert integrity['passed'] and integrity['coverage']['composed_lut_all_five_timing_arcs_present']
assert r['inputs_unchanged'] and r['timing']['completed'] and r['clock_targets_restored']
assert r['placement_unchanged'] and r['no_combinational_loop_warning'] and r['graph_analysis_completed']
assert r['command'][r['command'].index('--freq') + 1] == '100'
assert not any(x in r['command'] for x in ['--force', '--timing-allow-fail', '--ignore-loops'])
clocks = r['timing']['final_clocks']
assert clocks['clk']['mhz'] > 100 and clocks['soc.cpu_clk']['mhz'] > 100
assert all(c['status'] == 'PASS' for c in clocks.values())
crossings = r['timing']['cross_clock_delays']
assert len(crossings) == 2 and all(c['margin_ns'] >= 0 for c in crossings)
primitive = read(root / 'build-ddr-decode5-primitive-proof/results.json')
assert primitive['passed'] and primitive['exhaustive_assignments'] == 32
control = read(root / 'build-routing-import-unique-control-mid2-v3/manifest.json')
assert control['passed'] and control['timing_graph_exact'] and control['native_fmax_exact']
functional = []
for kind in ('dma', 'gemm'):
    source = read(root / f'build-ddr-{kind}-parallel-chooser-revalidated/system/results.json')
    current = read(root / f'build-ddr-{kind}-uart-local-burst-verified/system/results.json')
    assert all(source[k] == current[k] for k in ('profile', 'metrics', 'dma'))
    functional.append(dict(workload=kind, all_profile_metrics_dma_exact=True,
                           instructions=source['profile']['instructions'],
                           enabled_cpu_edges=source['profile']['cpu_edges'],
                           cpu_ipc=source['profile']['instructions'] / source['profile']['cpu_edges'],
                           system_cycles=source['metrics']['system_cycles'],
                           memory_model=source['metrics']['memory_model']))
board = root / 'build-ddr-dma-parallel-chooser/board'
current_board = root / 'build-ddr-dma-uart-local-burst/board'
for name in ('firmware.hex', 'kc705.xdc'):
    assert (board / name).read_bytes() == (current_board / name).read_bytes()
    checked[str(board / name)] = digest(board / name)
record = dict(passed=True, native_nextpnr_goal_met=True, native_partial_clocks=clocks,
              related_clock_crossings=crossings, functional=functional,
              scope='Native incomplete nextpnr report only. Reset copies and combinational decode are proved cycle equivalent; source workload simulations match current performance. No gate-level DDR3/PHY simulation or hardware validation.',
              full_soc_timing_accepted=False, physical_fmax_verified=False,
              checked_manifests=checked, script_sha256=digest(__file__))
(route / 'native-goal-verification.json').write_text(json.dumps(record, indent=2) + '\n')
print('PASS native nextpnr diagnostic target:', clocks['clk']['mhz'], 'MHz system /', clocks['soc.cpu_clk']['mhz'], 'MHz CPU; physical signoff remains open')
