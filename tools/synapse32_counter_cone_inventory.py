#!/usr/bin/env python3
"""Read-only inventory of late-control cones feeding DDR buffer counters."""
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_selector_patch_v4 import logical
p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();m=json.loads(a.checkpoint.read_text())['modules']['top'];cs=m['cells'];ls={}
for n,c in cs.items():
 if c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT'):ls[n]=logical(c)
 elif c['type']=='SELMUX2_1':ls[n]=(3,dict(I0=c['connections']['0'][0],I1=c['connections']['1'][0],I2=c['connections']['S0'][0],O=c['connections']['OUT'][0]),0xca)
drv={p['O']:n for n,(w,p,t) in ls.items()};g=next(n for n in ls if n.endswith('$217011'));gp=ls[g][1];ce=next(n for n in ls if n.endswith('$217100'));late=[gp['I0'],gp['I1'],ls[ce][1]['O']];memo={};active=set()
def dep(b):
 if b in late:return True
 if b in memo:return memo[b]
 if b not in drv:return False
 assert b not in active;active.add(b);w,p,_=ls[drv[b]];v=any(dep(p[f'I{i}']) for i in range(w));active.remove(b);memo[b]=v;return v
rows=[]
for alias,v in m['netnames'].items():
 if alias not in ['memory.main_write_id_buffer_level','memory.main_write_w_buffer_level2']:continue
 for bit in v['bits']:
  ff=next(n for n,c in cs.items() if c['type']=='SLICE_FFX' and c['connections'].get('Q')==[bit]);b=cs[ff]['connections']['D'][0];cone={};leaves=set()
  def walk(b):
   if b in late or not dep(b):leaves.add(b);return
   n=drv[b]
   if n in cone:return
   w,p,_=ls[n]
   for i in range(w):walk(p[f'I{i}'])
   cone[n]=cs[n]
  walk(b);rows.append(dict(group=alias,ff=ff,root=drv.get(b),root_type=cs[drv[b]]['type'] if b in drv else None,cone_cells=len(cone),cuts=sorted(leaves),late_cuts=sorted(set(leaves)&set(late))))
result=dict(scope='Read-only structural inventory; no equivalence or timing claim.',late_inputs=late,rows=rows,sha256={str(q.resolve()):digest(q) for q in [a.checkpoint,Path(__file__),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py')]});a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps([dict(group=v['group'],root_type=v['root_type'],cone_cells=v['cone_cells'],cuts=len(v['cuts']),late_cuts=len(v['late_cuts'])) for v in rows]))
