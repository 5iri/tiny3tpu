#!/usr/bin/env python3
"""Summarize stock-column diagnostics without mixing all-column timing scores."""
import argparse, hashlib, json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--integrity',type=Path,nargs='+',required=True)
    p.add_argument('--comparison',type=Path,nargs='+',required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--control',type=Path,nargs='*',default=[])
    p.add_argument('--fixed-integrity',type=Path,nargs='*',default=[])
    a=p.parse_args();assert not a.out.exists()
    hashes={};seen=set()
    def digest(path):
        path=Path(path).resolve();key=str(path)
        if key not in hashes:
            h=hashlib.sha256()
            with path.open('rb') as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
            hashes[key]=h.hexdigest()
        return hashes[key]
    def verify(path):
        path=Path(path).resolve();data=json.loads(path.read_text());digest(path)
        if path in seen:return data
        seen.add(path)
        for key in ['sha256','output_sha256']:
            for name,h in data.get(key,{}).items():assert digest(name)==h,(path,name)
        for r in data.get('checked_manifests',[]):
            assert digest(r['path'])==r['sha256'];verify(r['path'])
        return data
    records=[]
    for path in a.integrity:
        d=verify(path);assert d['passed'] and d['timing_model_category']=='stock_kc705_registered_primitives'
        assert not d['full_soc_timing_accepted'] and d['firmware_identical'] and d['constraints_identical']
        route=verify(Path(d['route'])/'manifest.json');assert route['grade_selection'] and route['domain_criticality_enabled']
        records.append(dict(kind='fresh_stock_column_guided_route',integrity=str(path.resolve()),route=d['route'],
            expanded_probes_ns=d['expanded_intervals_ns'],native_clocks=route['timing']['final_clocks'],
            standalone_dsp_slots_enabled=route.get('standalone_dsp_slots_enabled',False),upper_slot_dsp_count=route.get('upper_slot_dsp_count'),
            beta=route['placement_beta'],timing_weight=route['placement_timing_weight'],functional=d['functional'],
            new_workload_simulation_run=d['new_workload_simulation_run'],full_soc_timing_accepted=False))
    for path in a.fixed_integrity:
        d=verify(path);assert d['passed'] and d['kind'] in ['fixed_stock_column_route','fixed_stock_column_logic_patch'] and d['clocks_restored_without_period_changes']
        if d['kind']=='fixed_stock_column_route':assert d['logical_cells_exact']
        else:assert not d['logical_cells_exact'] and d['logical_cells_match_proved_patch'] and verify(d['patch'])['passed']
        assert d['timing_model_category']=='stock_kc705_registered_primitives' and not d['full_soc_timing_accepted']
        records.append(dict(kind=d['kind'],patch=d.get('patch'),integrity=str(path.resolve()),route=d['route'],normalized=d['normalized'],expanded_probes_ns=d['expanded_intervals_ns'],native_clocks=d['native_clocks'],placement_changes=d['placement_changes'],functional=d['functional'],new_workload_simulation_run=False,full_soc_timing_accepted=False))
    for path in a.comparison:
        d=verify(path);assert d['passed']
        records.append(dict(kind='same_route_stock_column_reanalysis',comparison=str(path.resolve()),
            expanded_probes_ns=[v['grade2_ns'] for v in d['variants']],
            meaning='Only registered-primitive timing column changed; not a new route or hardware speedup.',full_soc_timing_accepted=False))
    assert len(a.integrity)==len(set(a.integrity)) and len(a.comparison)==len(set(a.comparison))
    assert len(a.fixed_integrity)==len(set(a.fixed_integrity)) and not set(a.integrity)&set(a.fixed_integrity)
    controls=[]
    for path in a.control:
        d=verify(path);assert d['passed']
        controls.append(dict(path=str(path.resolve()),passed=True,full_soc_timing_accepted=False))
    best=min(records,key=lambda r:max(r['expanded_probes_ns']))
    digest(Path(__file__))
    result=dict(passed=True,category='stock_kc705_registered_primitives',records=records,controls=controls,
        best_diagnostic=best,all_column_stress_results_separate=True,full_soc_timing_accepted=False,
        limitations='Registered DSP/RAM/LUTRAM limits assume stock -2 / 1.0 V. Carry/cascade probes remain symbolic. Generic delays, clock skew/hold, reset recovery/removal and DDR IO remain unvalidated. No physical closure or promotion.',
        checked_manifests=[dict(path=str(q.resolve()),sha256=digest(q)) for q in a.integrity+a.comparison+a.control+a.fixed_integrity],sha256=hashes)
    a.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,fresh_routes=len(a.integrity),fixed_routes=len(a.fixed_integrity),reanalyses=len(a.comparison),hashes=len(hashes),best_probes_ns=best['expanded_probes_ns'],full_soc_timing_accepted=False)))

if __name__=='__main__':main()
