"""Run normalization, expanded timing probes and coverage for a completed incremental route."""
import argparse,json,subprocess,sys
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);a=p.parse_args();r=a.route.resolve();root=Path(__file__).resolve().parents[1];m=json.loads((r/'manifest.json').read_text());assert m['passed'] and m['logical_ports_exact'];n=Path(str(r)+'-normalized');t=Path(str(r)+'-timing');c=Path(str(r)+'-coverage')
steps=[(['synapse32_normalize_incremental_route.py','--control',str(r),'--out',str(n)],{0}),(['synapse32_route_timing_sensitivity_grade2.py','--route',str(n),'--out',str(t),'--expected-cascades','0'],{0}),(['synapse32_check_soc_timing.py','--route',str(n),'--sensitivity',str(t),'--out',str(c)],{0,2})]
for i,(args,codes) in enumerate(steps):
 with (r/f'evaluate-step-{i}.log').open('w') as f:rc=subprocess.run([sys.executable,str(root/'tools'/args[0]),*args[1:]],cwd=root,stdout=f,stderr=subprocess.STDOUT).returncode
 assert rc in codes,(i,rc);print('completed analysis step',i,flush=True)
report=json.loads((c/'report.json').read_text());assert report['native_fmax_reproduced'];timing=json.loads((t/'manifest.json').read_text());values=[max(v['arrival_ns'] for v in case['maxima']) for case in timing['variants']];paths=[r/'manifest.json',n/'manifest.json',t/'manifest.json',c/'report.json',Path(__file__).resolve()]
for q in paths[:-1]:
 v=json.loads(q.read_text())
 for key in ['sha256','output_sha256']:
  for f,h in v.get(key,{}).items():assert digest(f)==h
result=dict(passed=True,expanded_intervals_ns=values,full_soc_timing_accepted=False,new_workload_simulation_run=False,scope='Completed exact-equivalent incremental route diagnostic. Physical signoff remains unproven.',sha256={str(q):digest(q) for q in paths});out=r/'evaluation.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
