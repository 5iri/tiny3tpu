#!/usr/bin/env python3
"""Bind proved netlist transforms and actual routes to the stock KC705 limits."""
import argparse,json,subprocess,sys
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_kc705_grade2_limits import bram_limits,dsp_limits,lutram_limits,verify_board
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
for k in ['candidate','route','sensitivity','check','focused','out']:p.add_argument('--'+k,type=Path,required=True)
p.add_argument('--transform',choices=['wb_lut','sign_luts','branch_predicate','guarded_branch','local_branch','branch_carry','unused_a'],required=True);a=p.parse_args();assert not a.out.exists();base=a.out.with_suffix('.base.json');assert not base.exists()
helper=ROOT/'tools'/{'wb_lut':'synapse32_wb_lut_iteration_audit.py','sign_luts':'synapse32_sign_luts_iteration_audit.py','branch_predicate':'synapse32_branch_predicate_iteration_audit.py','guarded_branch':'synapse32_guarded_branch_iteration_audit.py','local_branch':'synapse32_local_branch_iteration_audit.py','branch_carry':'synapse32_branch_carry_iteration_audit.py','unused_a':'synapse32_unused_a_iteration_audit.py'}[a.transform];command=[sys.executable,str(helper)]
for k in ['candidate','route','sensitivity','check','focused']:command+=['--'+k,str(getattr(a,k))]
command+=['--out',str(base)];subprocess.run(command,check=True)
record=json.loads(base.read_text());assert record['passed'];route=json.loads((a.route/'manifest.json').read_text());model=json.loads((a.sensitivity/'manifest.json').read_text());assert route['domain_criticality_enabled'] and route['grade_selection'] and model['grade_selection']
assert .3<=route['placement_beta']<=.7 and f"HeAP congestion knobs: beta={route['placement_beta']:.3f}" in (a.route/'route.log').read_text()
board=verify_board();data=ROOT/'build-dsp-preg-timing/ds182.txt';expected=dict(bram=bram_limits(data.read_text()),dsp=dsp_limits(data.read_text()),lutram=lutram_limits(data.read_text()));assert model['limits']==json.loads(json.dumps(expected))
backend=Path(route['command'][0]);build_path=backend.with_name('build-manifest.json');build=json.loads(build_path.read_text());assert build['passed'] and build['baseline_unchanged']  and digest(backend)==build['tool_sha256']
for name,h in build['baseline_sha256'].items():assert digest(name)==h
assert route['standalone_dsp_slots_enabled']
grade_dir=Path('/tmp/tiny3tpu-nextpnr-grade2-guidance').resolve();grade_path=grade_dir/'build-manifest.json';grade=json.loads(grade_path.read_text());assert grade['passed'] and grade['grade_selection'] and digest(grade_dir/'domain_criticality.h')==grade['domain_header_sha256']
for name,h in grade['baseline_sha256'].items():assert digest(name)==h
tests_path=ROOT/'build-free-dsp-slots-pack-tests-v2/results.json';tests=json.loads(tests_path.read_text());assert tests['passed'] and [v['released'] for v in tests['tests']]==[36,34]
for key in ['sha256','output_sha256']:
 for name,h in tests[key].items():assert digest(name)==h
for n,k in [('pack_dsp_xc7.cc','source_sha256'),('pack_dsp.patch','patch_sha256'),('pack_dsp.o','object_sha256')]:assert digest(backend.with_name(n))==build[k]
cells=json.loads((a.route/'routed.json').read_text())['modules']['top']['cells'];bels={n:c['attributes']['NEXTPNR_BEL'] for n,c in cells.items() if c['type']=='DSP48E1_DSP48E1'};assert bels==route['dsp_bels'] and len(bels)==36
assert route['upper_slot_dsp_count']==sum(int(v.split('Y')[1].split('/')[0])%2 for v in bels.values())
replay_path=ROOT/'build-free-dsp-slots-disabled-replay/manifest.json';replay=json.loads(replay_path.read_text());assert replay['passed'] and replay['routed_json_exact'] and replay['timing_graph_exact'] and replay['native_fmax_exact']
for k in ['sha256','output_sha256']:
 for name,h in replay[k].items():assert digest(name)==h
assert replay['sha256'][str(backend)]==digest(backend)
for q in [base,board,build_path,replay_path,grade_path,tests_path]:record['checked_manifests'].append(dict(path=str(q.resolve()),sha256=digest(q)))
record['sha256'].update({str(q.resolve()):digest(q) for q in [Path(__file__),ROOT/'tools/synapse32_kc705_grade2_limits.py']})
record.update(standalone_dsp_slots_enabled=True,upper_slot_dsp_count=route['upper_slot_dsp_count'],timing_model_category='stock_kc705_registered_primitives',grade_selection=model['grade_selection'],placement_beta=route['placement_beta'],placement_timing_weight=route['placement_timing_weight'],scope=record['scope']+' Registered DSP, boot RAM and LUTRAM values use the documented stock -2 / 1.0 V column. Native rows match independent grade-column models. Disabled replay is exact. These intervals are separate from all-column stress comparisons; physical timing remains unaccepted.')
a.out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(dict(passed=True,expanded_intervals_ns=record['expanded_intervals_ns'],timing_model_category=record['timing_model_category'],full_soc_timing_accepted=False)))
