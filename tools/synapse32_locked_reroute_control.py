"""Reroute an unchanged lossless checkpoint with every imported route locked."""
import argparse,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();r=a.route.resolve();out=a.out.resolve();assert not out.exists();record=json.loads((r/'manifest.json').read_text());assert record['passed'];assert json.loads((r/'iteration-integrity.json').read_text())['passed'];source=r/'routed.json';assert digest(source)==record['output_sha256'][str(source)];gold=json.loads(source.read_text());gate=json.loads(source.read_text());count=0
for m in gate['modules'].values():
 for v in m['netnames'].values():
  route=v.get('attributes',{}).get('ROUTING','').strip()
  if not route:continue
  pieces=route.split(';');assert len(pieces)%3==0
  for i in range(0,len(pieces),3):
   assert not pieces[i+1] or pieces[i+1].startswith('PIPIDX/');pieces[i+2]='4'
  v['attributes']['ROUTING']=';'.join(pieces);count+=1
assert functional_cells(gold)[0]==functional_cells(gate)[0];out.mkdir();inp=out/'input.json';inp.write_text(json.dumps(gate,separators=(',',':'))+'\n');cmd=record['command'].copy()
for flag,path in [('--json',inp),('--write',out/'routed.json'),('--report',out/'report.json'),('--log',out/'route.log')]:cmd[cmd.index(flag)+1]=str(path)
cmd+=['--no-place'];assert '--no-route' not in cmd and '--fasm' not in cmd
paths=[source,r/'manifest.json',r/'iteration-integrity.json',inp,Path(cmd[0]),Path(cmd[cmd.index('--chipdb')+1]),Path(cmd[cmd.index('--xdc')+1]),Path(__file__).resolve()];hashes={str(q):digest(q) for q in paths};result=dict(passed=False,source=str(source),command=cmd,locked_nets=count,sha256=hashes,scope='Unchanged checkpoint only; every imported route locked. Full router executes; no new placement is needed for an unchanged verified layout.',full_soc_timing_accepted=False);manifest=out/'manifest.json';manifest.write_text(json.dumps(result,indent=2)+'\n');env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))};env.update(TINY3TPU_LOSSLESS_ROUTE_NAMES='1',NEXTPNR_DUMP_INVALID_TILE='1',TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS='1',TINY3TPU_CARRY_GUIDANCE_PS='100',TINY3TPU_PRIMITIVE_GUIDANCE='1',TINY3TPU_DOMAIN_CRITICALITY='1',NEXTPNR_PLACER_BETA=str(record['placement_beta']),TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'))
with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
result.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in hashes.items()))
if rc==0:
 actual=json.loads((out/'routed.json').read_text());result['logical_ports_exact']=functional_cells(gold)[0]==functional_cells(actual)[0]
 def bels(d):return {n:c['attributes'].get('NEXTPNR_BEL') for n,c in d['modules']['top']['cells'].items()}
 def routes(d):
  rows={}
  for n,v in d['modules']['top']['netnames'].items():
   route=v.get('attributes',{}).get('ROUTING','').strip()
   if route:
    parts=route.split(';');assert len(parts)%3==0;rows[n]=sorted((parts[i],parts[i+1]) for i in range(0,len(parts),3))
  return rows
 result['bels_exact']=bels(gold)==bels(actual);result['routing_exact']=routes(gold)==routes(actual);result['graph_exact']=digest(out/'guidance-timing-graph.tsv')==digest(r/'guidance-timing-graph.tsv');result['passed']=all(result[k] for k in ['inputs_unchanged','logical_ports_exact','bels_exact','routing_exact','graph_exact'])
result['output_sha256']={str(q):digest(q) for q in out.iterdir() if q.is_file() and q!=manifest};manifest.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['command','sha256','output_sha256']}));assert result['passed'],manifest
