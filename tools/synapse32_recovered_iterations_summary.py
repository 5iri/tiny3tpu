#!/usr/bin/env python3
"""Summarize the fully revalidated active candidates after toolchain recovery."""
import gc
gc.disable()
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes_v2 import RecoveredHashes
p=argparse.ArgumentParser();p.add_argument('--recovery',type=Path,required=True);p.add_argument('--legacy-recovery',nargs=2,type=Path,required=True);p.add_argument('--integrity',nargs='+',type=Path,required=True);p.add_argument('--control',nargs='*',type=Path,default=[]);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();recovery=RecoveredHashes(a.recovery,a.legacy_recovery);seen={};hashes={}
def verify(path):
 path=Path(path).resolve()
 if path in seen:return seen[path]
 d=json.loads(path.read_text());seen[path]=d;hashes[str(path)]=digest(path)
 for key in ['sha256','output_sha256','baseline_sha256']:
  for n,h in d.get(key,{}).items():hashes[str(Path(n).resolve())]=recovery.check(n,h)
 for r in d.get('checked_manifests',[]):recovery.check(r['path'],r['sha256']);verify(r['path'])
 return d
records=[];functional=None
assert len(set(p.resolve() for p in a.integrity))==len(a.integrity)
for p in a.integrity:
 d=verify(p);assert d['passed'] and d['kind']=='fixed_stock_column_logic_patch' and d['logical_cells_match_proved_patch'];assert d['timing_model_category']=='stock_kc705_registered_primitives' and not d['full_soc_timing_accepted'] and not d['new_workload_simulation_run']
 patch=verify(d['patch']);assert patch['passed'] and patch['added_latency_cycles']==0
 raw=verify(Path(d['route'])/'manifest.json');assert raw['passed'] and raw['clock_constraints_applied'] and raw['inputs_unchanged']
 assert raw['command'][raw['command'].index('--seed')+1]=='5' and raw['command'][raw['command'].index('--freq')+1]=='100'
 if functional is None:functional=d['functional']
 else:assert d['functional']==functional
 records.append(dict(integrity=str(p.resolve()),route=d['route'],patch=d['patch'],expanded_probes_ns=d['expanded_intervals_ns'],native_clocks=d['native_clocks'],original_cell_moves=len(d['placement_changes']),new_workload_simulation_run=False,full_soc_timing_accepted=False))
for p in a.control:assert verify(p)['passed']
best=min(records,key=lambda r:max(r['expanded_probes_ns']));paths=[Path(__file__),Path(__file__).with_name('synapse32_recovered_hashes_v2.py'),Path(__file__).with_name('synapse32_recovered_hashes.py'),a.recovery,*a.legacy_recovery];hashes.update({str(p.resolve()):digest(p) for p in paths})
result=dict(passed=True,kind='recovered_active_stock_column_candidates',recovery=recovery.metadata(),records=records,best_diagnostic=best,parent_functional= functional,full_soc_timing_accepted=False,scope='Active candidate series only. Complete current proofs, workload ancestry, raw routing, normalization and expanded timing are checked with explicit exact-replay tool recovery. Earlier broad experiment summaries are retained as history, not relabeled as newly reverified here. Generic/carry delays, clock skew/hold, reset and DDR IO remain unvalidated.',sha256=hashes)
a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(passed=True,candidates=len(records),hashes=len(hashes),best_probes_ns=best['expanded_probes_ns'],full_soc_timing_accepted=False)))
