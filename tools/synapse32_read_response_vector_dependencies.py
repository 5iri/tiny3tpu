#!/usr/bin/env python3
"""Check upstream early-cut independence for every encoded read-response branch."""
import argparse,json
from pathlib import Path
from synapse32_packed_read_response_encoded_branch import SELECTORS,logical
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());assert patch['passed'];source=Path(patch['checkpoint']).parent/'pre-fixup.json';m=json.loads(source.read_text())['modules']['top'];cs=m['cells'];drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};ls={n:logical(c) for n,c in cs.items() if (c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT')) or c['type']=='SELMUX2_1'};records=[]
for part in patch['components']:
 late={105590,SELECTORS[part['selector_id']]};memo={};active=set();frontier={}
 def dep(b):
  if b in late:return True
  if b in memo:return memo[b]
  n=drv.get(b)
  assert n is not None,('unresolved input',b)
  c=cs[n]
  if n in ls:w,p,_=ls[n];ins=[p[f'I{i}'] for i in range(w)]
  elif c['type']=='CARRY4':ins=[b for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for b in bs]
  else:
   frontier[n]=c['type'];assert c['type'] in ['SLICE_FFX','GND','VCC','PSEUDO_GND','PSEUDO_VCC'],(n,c['type']);return False
  assert b not in active;active.add(b);v=any(dep(x) for x in ins);active.remove(b);memo[b]=v;return v
 early=sorted({b for n in part['read_response_early_cells'] for p,bs in part['added_cells'][n]['connections'].items() if part['added_cells'][n]['port_directions'][p]=='input' for b in bs});results={b:dep(b) for b in early};assert not any(results.values());records.append(dict(selector=part['selector_id'],late=sorted(late),early=early,dependent=results,frontier=frontier))
a.out.write_text(json.dumps(dict(passed=True,branches=records,sha256={str(q.resolve()):digest(q) for q in [a.patch,source,Path(__file__),Path(__file__).with_name('synapse32_packed_read_response_encoded_branch.py')]}),indent=2)+'\n');print('PASS: all eight early-cut sets independent, with only register/constant frontiers')
