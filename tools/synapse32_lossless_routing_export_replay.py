"""Replay an unchanged routed checkpoint and export routes without running P&R."""
import argparse,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--tool',type=Path,required=True);p.add_argument('--enable-lossless-route-names',action='store_true');a=p.parse_args();r=a.route.resolve();out=a.out.resolve();assert not out.exists();record=json.loads((r/'manifest.json').read_text());assert record['passed'];source=r/'routed.json';assert digest(source)==record['output_sha256'][str(source)];integrity=r/'iteration-integrity.json';assert json.loads(integrity.read_text())['passed'];cmd=record['command'].copy();cmd[0]=str(a.tool.resolve());build=a.tool.resolve().parent/'manifest.json';bm=json.loads(build.read_text());assert bm['passed'] and digest(a.tool)==bm['tool_sha256']
for flag in ['--placer','--starttemp']:
 i=cmd.index(flag);del cmd[i:i+2]
for flag,path in [('--json',source),('--write',out/'routed.json'),('--report',out/'report.json'),('--log',out/'replay.log')]:cmd[cmd.index(flag)+1]=str(path)
cmd+=['--no-place','--no-route','--write-fixed-routes',str(out/'fixed-routes.txt')];assert '--fasm' not in cmd
inputs=[build,source,r/'manifest.json',integrity,Path(cmd[0]),Path(cmd[cmd.index('--chipdb')+1]),Path(cmd[cmd.index('--xdc')+1]),Path(__file__).resolve()];hashes={str(q):digest(q) for q in inputs};out.mkdir();result=dict(passed=False,kind='unchanged_routed_export_replay',command=cmd,source=str(source),sha256=hashes,new_route_run=False,full_soc_timing_accepted=False);manifest=out/'manifest.json';manifest.write_text(json.dumps(result,indent=2)+'\n');env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))}
if a.enable_lossless_route_names:env['TINY3TPU_LOSSLESS_ROUTE_NAMES']='1'
with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
result['exit_code']=rc;result['inputs_unchanged']=all(digest(n)==h for n,h in hashes.items())
if rc==0:
 gold=json.loads(source.read_text());actual=json.loads((out/'routed.json').read_text());result['logical_ports_exact']=functional_cells(gold)[0]==functional_cells(actual)[0]
 def bels(d):return {n:c['attributes'].get('NEXTPNR_BEL') for n,c in d['modules']['top']['cells'].items()}
 def routes(d):
  rows={}
  for n,v in d['modules']['top']['netnames'].items():
   route=v.get('attributes',{}).get('ROUTING','').strip()
   if route:
    parts=route.split(';');assert len(parts)%3==0;rows[n]=sorted(tuple(parts[i:i+3]) for i in range(0,len(parts),3))
  return rows
 result['bels_exact']=bels(gold)==bels(actual);gr,ar=routes(gold),routes(actual);result['routing_exact']=gr==ar;result['routed_nets']=len(gr);result['exported_route_lines']=sum(1 for l in (out/'fixed-routes.txt').open() if l.strip() and not l.startswith('#'));result['passed']=all(result[k] for k in ['inputs_unchanged','logical_ports_exact','bels_exact','routing_exact'])
result['output_sha256']={str(q):digest(q) for q in out.iterdir() if q.is_file() and q!=manifest};manifest.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['command','sha256','output_sha256']}));assert result['passed'],manifest
