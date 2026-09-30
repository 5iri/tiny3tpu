"""Execute all predeclared OR/carry paired seeds with full route and timing audits."""
import json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
root=Path(__file__).resolve().parents[1];planpath=root/'build-grade2-or-carry-paired-seed-plan.json';plan=json.loads(planpath.read_text());assert plan['passed'] and plan['declared_seed_set']==[4,5,6]
for n,h in plan['sha256'].items():assert digest(n)==h,n
families={'baseline':'read_or_arrival_partition','candidate':'joint_carry_read_or_partition'}
status=root/'build-grade2-or-carry-paired-seed-status.json';assert not status.exists();record=dict(passed=False,plan=str(planpath),plan_sha256=digest(planpath),runner_sha256=digest(Path(__file__)),completed=[],active=None,full_soc_timing_accepted=False)
def update(active):
 record['active']=active;status.write_text(json.dumps(record,indent=2)+'\n')
def run(cmd,log,expected=0):
 with log.open('w') as f:rc=subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT).returncode
 assert rc==expected,(cmd,rc,str(log))
def collect(role,seed,integrity):
 ip=root/integrity;d=json.loads(ip.read_text());assert d['passed'];route=Path(d['route']);rm=json.loads((route/'manifest.json').read_text());assert Path(rm['patch']).resolve()==(root/plan['patches'][role]).resolve();assert int(rm['command'][rm['command'].index('--seed')+1])==seed
 actual=json.loads((route/'routed.json').read_text());assert int(actual['modules']['top']['settings']['seed.arg'],2)==seed
 if seed!=5:assert d['seed']==seed and d['actual_seed_verified']
 return dict(role=role,seed=seed,integrity=str(ip),sha256=digest(ip),expanded_intervals_ns=d['expanded_intervals_ns'],worst_ns=max(d['expanded_intervals_ns']))
rows=[collect(role,5,plan['existing_seed5_integrities'][role]) for role in families]
recovery=['--recovery','build-toolchain-recovery/transport-replay/manifest.json'];legacy=['--legacy-recovery','build-toolchain-recovery/mixed-replay/manifest.json','build-toolchain-recovery/cpu-preg-replay/manifest.json']
for case in plan['new_run_order']:
 role,seed=case['role'],case['seed'];family=families[role];stem=f'build-grade2-or-carry-seed-{role}-{seed}';r=stem+'-route';n=stem+'-normalized';s=stem+'-timing';c=stem+'-coverage'
 update(dict(role=role,seed=seed,phase='route'));run(['python3',f'tools/synapse32_grade2_fixed_{family}_seed.py','--checkpoint','build-grade2-choice-checkpoint-replay',*recovery,'--patch',plan['patches'][role],'--seed',str(seed),'--out',r],root/'build-toolchain-recovery'/f'or-carry-seed-{role}-{seed}-route-driver.log')
 commands=[['python3',f'tools/synapse32_normalize_pinmap_{family}_seed.py','--control',r,'--out',n],['python3','tools/synapse32_route_timing_sensitivity_grade2.py','--route',n,'--out',s,'--expected-cascades','0'],['python3','tools/synapse32_check_soc_timing.py','--route',n,'--sensitivity',s,'--out',c],['python3',f'tools/synapse32_fixed_{family}_seed_audit.py',*recovery,*legacy,'--route',r,'--normalized',n,'--sensitivity',s,'--check',c,'--out',r+'/iteration-integrity.json']]
 for i,cmd in enumerate(commands):update(dict(role=role,seed=seed,phase='analysis',step=i));run(cmd,root/r/f'analysis-step-{i}.log',2 if i==2 else 0)
 row=collect(role,seed,r+'/iteration-integrity.json');rows.append(row);record['completed'].append(row);update(None);print(json.dumps(row),flush=True)
assert {(r['role'],r['seed']) for r in rows}=={(r,s) for r in families for s in [4,5,6]} and len(rows)==6
for r in rows:assert digest(r['integrity'])==r['sha256']
summary=root/'build-grade2-or-carry-paired-seed-summary.json';assert not summary.exists();summary.write_text(json.dumps(dict(passed=True,cases=rows,paired_deltas_ns={str(s):next(r['worst_ns'] for r in rows if r['role']=='candidate' and r['seed']==s)-next(r['worst_ns'] for r in rows if r['role']=='baseline' and r['seed']==s) for s in [4,5,6]},scope='Every predeclared design/seed case, not physical timing signoff or statistical robustness beyond these samples.',full_soc_timing_accepted=False,sha256={str(planpath):digest(planpath),str(Path(__file__).resolve()):digest(Path(__file__))}),indent=2)+'\n');record['passed']=True;record['summary_sha256']=digest(summary);update(None);print('PASS complete paired seed comparison; physical timing remains unaccepted',flush=True)
