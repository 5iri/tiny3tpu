#!/usr/bin/env python3
"""Bind proved netlist transforms and actual routes to the stock KC705 limits."""
import argparse,json,subprocess,sys
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_kc705_grade2_limits import bram_limits,dsp_limits,lutram_limits,verify_board
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
for k in ['candidate','route','sensitivity','check','focused','out']:p.add_argument('--'+k,type=Path,required=True)
p.add_argument('--transform',choices=['wb_lut','sign_luts','branch_predicate','guarded_branch','local_branch','branch_carry','unused_a','zqcs_zero','mux_lut','sequencer_choice','multiply_mode','ddr_compare_choice','dma_descriptor_choice'],required=True);a=p.parse_args();assert not a.out.exists();base=a.out.with_suffix('.base.json');assert not base.exists()
helper=ROOT/'tools'/{'wb_lut':'synapse32_wb_lut_iteration_audit.py','sign_luts':'synapse32_sign_luts_iteration_audit.py','branch_predicate':'synapse32_branch_predicate_iteration_audit.py','guarded_branch':'synapse32_guarded_branch_iteration_audit.py','local_branch':'synapse32_local_branch_iteration_audit.py','branch_carry':'synapse32_branch_carry_iteration_audit.py','unused_a':'synapse32_unused_a_iteration_audit.py','zqcs_zero':'synapse32_zqcs_zero_iteration_audit.py','mux_lut':'synapse32_mux_lut_iteration_audit.py','sequencer_choice':'synapse32_sequencer_choice_iteration_audit.py','multiply_mode':'synapse32_multiply_mode_iteration_audit_v2.py','ddr_compare_choice':'synapse32_ddr_compare_choice_iteration_audit.py','dma_descriptor_choice':'synapse32_dma_descriptor_choice_iteration_audit.py'}[a.transform];command=[sys.executable,str(helper)]
for k in ['candidate','route','sensitivity','check','focused']:command+=['--'+k,str(getattr(a,k))]
command+=['--out',str(base)];subprocess.run(command,check=True)
record=json.loads(base.read_text());assert record['passed'];route=json.loads((a.route/'manifest.json').read_text());model=json.loads((a.sensitivity/'manifest.json').read_text());assert route['domain_criticality_enabled'] and route['grade_selection'] and model['grade_selection']
assert .3<=route['placement_beta']<=.7 and f"HeAP congestion knobs: beta={route['placement_beta']:.3f}" in (a.route/'route.log').read_text()
board=verify_board();data=ROOT/'build-dsp-preg-timing/ds182.txt';expected=dict(bram=bram_limits(data.read_text()),dsp=dsp_limits(data.read_text()),lutram=lutram_limits(data.read_text()));assert model['limits']==json.loads(json.dumps(expected))
backend=Path(route['command'][0]);build_path=backend.with_name('build-manifest.json');build=json.loads(build_path.read_text());assert build['passed'] and build['baseline_unchanged'] and build['grade_selection'] and digest(backend)==build['tool_sha256']
for name,h in build['baseline_sha256'].items():assert digest(name)==h
assert digest(backend.with_name('domain_criticality.h'))==build['domain_header_sha256']
replay_path=ROOT/'build-grade2-guidance-disabled-replay/manifest.json';replay=json.loads(replay_path.read_text());assert replay['passed'] and replay['routed_json_exact'] and replay['timing_graph_exact'] and replay['native_fmax_exact']
for k in ['sha256','output_sha256']:
 for name,h in replay[k].items():assert digest(name)==h
assert replay['sha256'][str(backend)]==digest(backend)
for q in [base,board,build_path,replay_path]:record['checked_manifests'].append(dict(path=str(q.resolve()),sha256=digest(q)))
record['sha256'].update({str(q.resolve()):digest(q) for q in [Path(__file__),ROOT/'tools/synapse32_kc705_grade2_limits.py']})
record.update(timing_model_category='stock_kc705_registered_primitives',grade_selection=model['grade_selection'],placement_beta=route['placement_beta'],placement_timing_weight=route['placement_timing_weight'],scope=record['scope']+' Registered DSP, boot RAM and LUTRAM values use the documented stock -2 / 1.0 V column. Native rows match independent grade-column models. Disabled replay is exact. These intervals are separate from all-column stress comparisons; physical timing remains unaccepted.')
a.out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(dict(passed=True,expanded_intervals_ns=record['expanded_intervals_ns'],timing_model_category=record['timing_model_category'],full_soc_timing_accepted=False)))
