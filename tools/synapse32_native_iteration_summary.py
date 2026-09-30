#!/usr/bin/env python3
"""Bind the native-report milestone and expanded-model limitation to exact artifacts."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
checked = {}


def read(path):
    data = json.loads(path.read_text())
    for key in ('sha256', 'output_sha256'):
        for name, value in data.get(key, {}).items():
            assert digest(name) == value, (str(path), name)
    checked[str(path)] = digest(path)
    return data


selected = root / 'build-ddr-route-reset-decode5-pe-seed4'
goal = read(selected / 'native-goal-verification.json')
assert goal['passed'] and goal['native_nextpnr_goal_met'] and not goal['physical_fmax_verified']
for name, value in goal['checked_manifests'].items():
    assert digest(name) == value, name
routes = []
for folder in (
    'build-ddr-route-reset-unique-locked-seed2',
    'build-ddr-route-reset-unique-unlocked-seed2',
    'build-ddr-route-reset-unique-locked-seed4',
    'build-ddr-route-reset-unique-locked-seed8',
    'build-ddr-route-reset-decode5-seed2',
    'build-ddr-route-reset-decode5-seed4',
    'build-ddr-route-reset-decode5-timer-seed2',
    'build-ddr-route-reset-decode5-timer-seed4',
    'build-ddr-route-reset-decode5-tpu-seed2',
    'build-ddr-route-reset-decode5-tpu-seed4',
    'build-ddr-route-reset-decode5-tpu-timer-seed2',
    'build-ddr-route-reset-decode5-tpu-timer-seed4',
    'build-ddr-route-reset-decode5-timers-seed4',
    'build-ddr-route-reset-decode5-timers-bus-seed2',
    'build-ddr-route-reset-decode5-timers-bus-seed4',
    'build-ddr-route-reset-decode5-timers-two-seed4',
    'build-ddr-route-reset-decode5-pe-seed4',
):
    data = read(root / folder / 'manifest.json')
    assert data['inputs_unchanged'] and data['placement_unchanged'] and data['clock_targets_restored']
    assert data['timing']['completed'] and data['graph_analysis_completed']
    assert data['no_combinational_loop_warning'] and not data['full_soc_timing_accepted']
    clocks = data['timing']['final_clocks']
    routes.append(dict(route=folder, system_mhz=clocks['clk']['mhz'], cpu_mhz=clocks['soc.cpu_clk']['mhz']))

models = []
for folder in ('build-ddr-reset-decode5-pe4-timing-sensitivity',
               'build-ddr-uart-reset-guided8-timing-sensitivity'):
    model = read(root / folder / 'manifest.json')
    assert not model['timing_audit_passed'] and not model['full_soc_timing_accepted']
    for v in model['variants']:
        p = root / folder / f"graph-pcout-{v['symbolic_pcout_ns']}-carry-{v['symbolic_carry_arc_ns']}.tsv"
        assert digest(p) == v['graph_sha256']
    models.append(dict(artifact=folder, symbolic_intervals_ns=[max(x['arrival_ns'] for x in v['maxima']) for v in model['variants']]))
assert min(models[0]['symbolic_intervals_ns']) > 10
assert max(models[1]['symbolic_intervals_ns']) < max(models[0]['symbolic_intervals_ns'])
result = dict(passed=True, native_nextpnr_goal_met=True,
              selected_native_route=str(selected), routes=routes, expanded_models=models,
              physical_fmax_verified=False, full_soc_timing_accepted=False,
              interpretation='Native >100 MHz report reached with cycle-equivalent changes. Expanded diagnostics still exceed 10 ns and this native winner does not replace the better expanded-model UART candidate. No board/default promotion.',
              checked_manifests=checked, script_sha256=digest(__file__))
(selected / 'iteration-summary.json').write_text(json.dumps(result, indent=2) + '\n')
print('PASS', len(routes), 'completed route records; native goal met; expanded model still exceeds 10 ns')
