"""Execute the frozen paired seed plan, with full independent audits for every route."""
import json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
root=Path(__file__).resolve().parents[1];planpath=root/'build-grade2-branch-carry-seed-plan-v2.json';plan=json.loads(planpath.read_text());assert plan['passed'] and plan['declared_seed_set']==[4,5,6]
for n,h in plan['sha256'].items():assert digest(n)==h,n
status=root/'build-grade2-branch-paired-seed-status-v2.json';assert not status.exists();record=dict(passed=False,plan=str(planpath),plan_sha256=digest(planpath),runner_sha256=digest(Path(__file__)),completed=[],active=None,full_soc_timing_accepted=False)
def update(active):
 record['active']=active;status.write_text(json.dumps(record,indent=2)+'\n')
def run(cmd,log,expected=0):
 with log.open('w') as f:rc=subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT).returncode
 if rc!=expected:
  record['error']=dict(command=cmd,exit_code=rc,expected_exit_code=expected,log=str(log));update(record['active']);raise AssertionError((cmd,rc,log))
recovery=['--recovery','build-toolchain-recovery/transport-replay/manifest.json'];legacy=['--legacy-recovery','build-toolchain-recovery/mixed-replay/manifest.json','build-toolchain-recovery/cpu-preg-replay/manifest.json'];integrities=['build-grade2-timer-mid-zero-flag-route/iteration-integrity.json','build-grade2-branch-carry-input-inline-route/iteration-integrity.json']
for seed in [4,6]:
 for role,family in [('baseline','timer_mid_zero_flag'),('candidate','branch_carry_input_inline')]:
  stem=f'build-grade2-branch-seed-v2-{role}-{seed}';r=stem+'-route';n=stem+'-normalized';s=stem+'-timing';c=stem+'-coverage';update(dict(role=role,seed=seed,phase='route'));run(['python3',f'tools/synapse32_grade2_fixed_{family}_seed_v2.py','--checkpoint','build-grade2-choice-checkpoint-replay',*recovery,'--patch',plan['patches'][role],'--seed',str(seed),'--out',r],root/'build-toolchain-recovery'/f'branch-seed-v2-{role}-{seed}-route-driver.log')
  commands=[['python3',f'tools/synapse32_normalize_pinmap_{family}_seed.py','--control',r,'--out',n],['python3','tools/synapse32_route_timing_sensitivity_grade2.py','--route',n,'--out',s,'--expected-cascades','0'],['python3','tools/synapse32_check_soc_timing.py','--route',n,'--sensitivity',s,'--out',c],['python3',f'tools/synapse32_fixed_{family}_seed_audit.py',*recovery,*legacy,'--route',r,'--normalized',n,'--sensitivity',s,'--check',c,'--out',r+'/iteration-integrity.json']]
  for i,cmd in enumerate(commands):update(dict(role=role,seed=seed,phase='analysis',step=i));run(cmd,root/r/f'analysis-step-{i}.log',2 if i==2 else 0)
  integrity=r+'/iteration-integrity.json';d=json.loads((root/integrity).read_text());assert d['passed'] and d['seed']==seed;record['completed'].append(dict(role=role,seed=seed,integrity=integrity,sha256=digest(root/integrity),expanded_intervals_ns=d['expanded_intervals_ns']));integrities.append(integrity);update(None);print(json.dumps(record['completed'][-1]),flush=True)
update(dict(phase='paired summary'));run(['python3','tools/synapse32_paired_seed_summary.py','--plan',str(planpath),'--integrity',*integrities,*recovery,*legacy,'--out','build-grade2-branch-paired-seed-summary-v2.json'],root/'build-toolchain-recovery'/'branch-paired-seed-summary-v2.log');record['passed']=True;record['summary_sha256']=digest(root/'build-grade2-branch-paired-seed-summary-v2.json');update(None);print('PASS complete paired seed comparison; full physical timing remains unaccepted',flush=True)
