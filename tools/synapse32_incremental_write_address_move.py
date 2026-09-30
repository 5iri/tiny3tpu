"""Move 13 unchanged FFs, release incident nets, and retain all other routed nets."""
import argparse,copy,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells
from synapse32_locked_reroute_evidence import routes
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);p.add_argument('--placement-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();r=a.route.resolve();out=a.out.resolve();assert not out.exists();record=json.loads((r/'manifest.json').read_text());assert record['passed'] and json.loads((r/'iteration-integrity.json').read_text())['passed'];source=r/'pre-fixup.json';assert digest(source)==record['output_sha256'][str(source)];gold=json.loads((r/'routed.json').read_text());gate=json.loads(source.read_text());prior=copy.deepcopy(gate);patch=json.loads(a.placement_patch.read_text());assert patch['passed'];cs=gate['modules']['top']['cells'];moves={n:[c['attributes']['NEXTPNR_BEL'],patch['placements'][n]] for n,c in cs.items() if n in patch['placements'] and c['attributes']['NEXTPNR_BEL']!=patch['placements'][n]};assert len(moves)==13
released_bits=set()
for n,(old,new) in moves.items():
 c=cs[n];assert c['type']=='SLICE_FFX' and c['attributes']['X_ORIG_TYPE']=='FDRE' and c['parameters']=={'INIT':'0'};released_bits.update(b for bs in c['connections'].values() for b in bs);c['attributes']['NEXTPNR_BEL']=new
for c in cs.values():c['attributes']['BEL_STRENGTH']=format(5,'032b')
assert len({c['attributes']['NEXTPNR_BEL'] for c in cs.values()})==len(cs);assert functional_cells(prior)[0]==functional_cells(gate)[0]==functional_cells(gold)[0]
released=[];locked=[]
for name,v in gate['modules']['top']['netnames'].items():
 if set(v['bits'])&released_bits:
  v.get('attributes',{}).pop('ROUTING',None);released.append(name);continue
 text=v.get('attributes',{}).get('ROUTING','').strip()
 if text:
  fields=text.split(';');assert len(fields)%3==0
  for i in range(0,len(fields),3):assert not fields[i+1] or fields[i+1].startswith('PIPIDX/');fields[i+2]='4'
  v['attributes']['ROUTING']=';'.join(fields);locked.append(name)
out.mkdir();inp=out/'input.json';inp.write_text(json.dumps(gate,separators=(',',':'))+'\n');cmd=record['command'].copy()
for flag,path in [('--json',inp),('--write',out/'routed.json'),('--report',out/'report.json'),('--log',out/'route.log')]:cmd[cmd.index(flag)+1]=str(path)
assert '--no-place' not in cmd and '--no-route' not in cmd and '--fasm' not in cmd
paths=[source,r/'routed.json',r/'manifest.json',r/'iteration-integrity.json',a.placement_patch.resolve(),inp,Path(cmd[0]),Path(cmd[cmd.index('--chipdb')+1]),Path(cmd[cmd.index('--xdc')+1]),Path(__file__).resolve()];hashes={str(q):digest(q) for q in paths};result=dict(passed=False,source=str(source),command=cmd,moves=moves,released_net_names=released,retained_net_names=locked,sha256=hashes,scope='Placement-only move of 13 original FFs; identical logical ports. Normal placement and routing, with nonincident routes locked.',full_soc_timing_accepted=False);manifest=out/'manifest.json';manifest.write_text(json.dumps(result,indent=2)+'\n');env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))};env.update(TINY3TPU_LOSSLESS_ROUTE_NAMES='1',NEXTPNR_DUMP_INVALID_TILE='1',TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS='1',TINY3TPU_CARRY_GUIDANCE_PS='100',TINY3TPU_PRIMITIVE_GUIDANCE='1',TINY3TPU_DOMAIN_CRITICALITY='1',NEXTPNR_PLACER_BETA=str(record['placement_beta']),TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'))
with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
result.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in hashes.items()))
if rc==0:
 actual=json.loads((out/'routed.json').read_text());result['logical_ports_exact']=functional_cells(gold)[0]==functional_cells(actual)[0];ac=actual['modules']['top']['cells'];result['placements_exact']=set(ac)==set(cs) and all(ac[n]['attributes']['NEXTPNR_BEL']==c['attributes']['NEXTPNR_BEL'] for n,c in cs.items());ar=routes(gold['modules']['top']);br=routes(actual['modules']['top']);result['retained_routes_exact']=all(ar[n]==br.get(n) for n in locked if n!='$PACKER_GND_NET');result['ground_additions_only']='$PACKER_GND_NET' not in locked or ar['$PACKER_GND_NET']<=br.get('$PACKER_GND_NET',set());result['passed']=all(result[k] for k in ['inputs_unchanged','logical_ports_exact','placements_exact','retained_routes_exact','ground_additions_only'])
result['output_sha256']={str(q):digest(q) for q in out.iterdir() if q.is_file() and q!=manifest};manifest.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['command','sha256','output_sha256','moves','released_net_names','retained_net_names']}));assert result['passed'],manifest
