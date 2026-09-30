"""Require the complete predeclared paired seed set before reporting variation."""
import argparse,json,statistics
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes_v2 import RecoveredHashes
p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--integrity',nargs=6,type=Path,required=True);p.add_argument('--recovery',type=Path,required=True);p.add_argument('--legacy-recovery',nargs=2,type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();plan=json.loads(a.plan.read_text());assert plan['declared_seed_set']==[4,5,6] and plan['freq_mhz']==100;recovery=RecoveredHashes(a.recovery,a.legacy_recovery);seen=set();hashes={};records=[];functional=None

def verify(p):
 p=Path(p).resolve();d=json.loads(p.read_text())
 if p in seen:return d
 seen.add(p);hashes[str(p)]=digest(p)
 for key in ['sha256','output_sha256','baseline_sha256']:
  for n,h in d.get(key,{}).items():hashes[str(Path(n).resolve())]=recovery.check(n,h)
 for r in d.get('checked_manifests',[]):assert recovery.check(r['path'],r['sha256']);verify(r['path'])
 return d
verify(a.plan);pairs=set()
for path in a.integrity:
 d=verify(path);assert d['passed'] and d['kind']=='fixed_stock_column_logic_patch' and d['logical_cells_match_proved_patch'] and not d['full_soc_timing_accepted'] and not d['new_workload_simulation_run'];assert d['timing_model_category']=='stock_kc705_registered_primitives'
 patch=verify(d['patch']);assert patch['added_latency_cycles']==0
 roles=[role for role,p in plan['patches'].items() if Path(p).resolve()==Path(d['patch']).resolve()];assert len(roles)==1;role=roles[0]
 raw=verify(Path(d['route'])/'manifest.json');assert raw['passed'] and raw['inputs_unchanged'] and raw['clock_constraints_applied'];cmd=raw['command'];seed=int(cmd[cmd.index('--seed')+1]);assert seed in plan['declared_seed_set'] and cmd[cmd.index('--freq')+1]=='100';assert cmd[0]==plan['backend'] and cmd[cmd.index('--chipdb')+1]==plan['chipdb']
 route=Path(d['route'])/'routed.json';actual=json.loads(route.read_text());assert int(actual['modules']['top']['settings']['seed.arg'],2)==seed;del actual
 assert (role,seed) not in pairs;pairs.add((role,seed))
 if seed!=5:assert d['seed']==raw['seed']==seed and raw['actual_seed_verified']
 if functional is None:functional=d['functional']
 else:assert d['functional']==functional
 records.append(dict(role=role,seed=seed,route=d['route'],integrity=str(path.resolve()),expanded_probes_ns=d['expanded_intervals_ns'],worst_ns=max(d['expanded_intervals_ns']),native_clocks=d['native_clocks']))
assert pairs=={(r,s) for r in ['baseline','candidate'] for s in [4,5,6]}
distribution={r:dict(min_ns=min(v),mean_ns=statistics.mean(v),max_ns=max(v),all_seeds_below_10_ns=all(x<10 for x in v)) for r in ['baseline','candidate'] for v in [[q['worst_ns'] for q in records if q['role']==r]]}
hashes.update({str(q.resolve()):digest(q) for q in [Path(__file__),a.recovery,*a.legacy_recovery,Path(__file__).with_name('synapse32_recovered_hashes_v2.py')]})
a.out.write_text(json.dumps(dict(passed=True,records=sorted(records,key=lambda r:(r['role'],r['seed'])),distribution=distribution,parent_functional=functional,new_workload_simulation_run=False,full_soc_timing_accepted=False,scope='Complete paired fixed-layout seed set, with identical parent firmware and clock constraints. Expanded diagnostic models remain unqualified for generic/carry delays, skew/hold, resets and DDR IO. No physical signoff.',sha256=hashes),indent=2)+'\n');print(json.dumps(dict(passed=True,distribution=distribution,full_soc_timing_accepted=False)))
