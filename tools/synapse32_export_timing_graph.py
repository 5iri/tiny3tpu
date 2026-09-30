#!/usr/bin/env python3
"""Replay a route with an isolated read-only timing graph observer."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
from synapse32_timing_report import summarize
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True);p.add_argument('--reporter',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
parent=a.parent.resolve();r=json.loads(parent.read_text());assert r['inputs_unchanged'] and r['timing']['completed'] and r['clock_targets_restored']
binary=a.reporter.resolve();bm=binary.with_name('build-manifest.json');b=json.loads(bm.read_text());assert b['passed'] and b['baseline_unchanged'] and digest(binary)==b['tool_sha256']
for n,h in b['baseline_sha256'].items():assert digest(n)==h,n
for n,k in [('timing.cc','source_sha256'),('timing.patch','patch_sha256'),('timing.o','object_sha256')]:assert digest(binary.with_name(n))==b[k]
cmd=list(r['command']);actual_inputs=[Path(cmd[0])]+[Path(cmd[cmd.index(f)+1]) for f in ['--json','--xdc','--chipdb']]
for q in actual_inputs:assert digest(q)==r['sha256'][str(q)],str(q)
# The old Python orchestration scripts are historical provenance, not replay
# inputs. The actual executable command and all its hardware inputs are checked.
out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);cmd[0]=str(binary)
for flag,v in [('--write',out/'routed.json'),('--report',out/'report.json'),('--log',out/'route.log')]:cmd[cmd.index(flag)+1]=str(v)
sha={str(q):digest(q) for q in actual_inputs+[parent,bm,binary,Path(__file__).resolve()]}
record={'parent':str(parent),'command':cmd,'sha256':sha,'scope':'Exact recorded router command and hardware inputs, using isolated optional live timing graph export. All timing equations and route/placement checks are unchanged. Historical orchestration scripts are not executed.','environment':{'TINY3TPU_TIMING_GRAPH':str(out/'timing-graph.tsv')}}
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
e={k:v for k,v in os.environ.items() if not k.startswith('NEXTPNR_')};e['TINY3TPU_TIMING_GRAPH']=str(out/'timing-graph.tsv')
with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env=e,stdout=f,stderr=subprocess.STDOUT).returncode
record['inputs_unchanged']=all(digest(n)==h for n,h in sha.items());record['timing']=summarize((out/'route.log').read_text(),exit_code=rc)
record['fmax_reproduced']={k:v['mhz'] for k,v in record['timing']['final_clocks'].items()}=={k:v['mhz'] for k,v in r['timing']['final_clocks'].items()}
old=json.loads(Path(r['command'][r['command'].index('--write')+1]).read_text());new=json.loads((out/'routed.json').read_text()) if rc==0 else None
record['routed_json_exact']=old==new
graph=out/'timing-graph.tsv'
record['graph_sha256']=digest(graph) if graph.exists() else None
record['passed']=record['inputs_unchanged'] and record['fmax_reproduced'] and record['routed_json_exact'] and graph.exists() and graph.stat().st_size>0
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print({k:v for k,v in record.items() if k not in ['sha256','command','timing']})
if not record['passed']:raise SystemExit('Timing graph replay did not reproduce the original route')
