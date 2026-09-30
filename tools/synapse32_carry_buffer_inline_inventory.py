"""Inventory carry-local identity LUTs that can absorb one upstream LUT exactly."""
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import logical,evaluate
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();rp=a.route.resolve()/'manifest.json';r=json.loads(rp.read_text());assert r['passed'];source=a.route.resolve()/'input.json';assert r['sha256'][str(source)]==digest(source);m=json.loads(source.read_text())['modules']['top'];cs=m['cells'];drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};bels={c['attributes']['NEXTPNR_BEL']:n for n,c in cs.items()};items=[]
for n,c in cs.items():
 if c['type']!='SLICE_LUTX' or c['attributes'].get('X_ORIG_TYPE')!='LUT1' or int(c['parameters']['INIT'],2)!=2:continue
 parent=c['attributes'].get('CONSTR_PARENT')
 if parent not in cs or cs[parent]['type']!='CARRY4':continue
 w,p,t=logical(c);assert w==1;up=drv[p['I0']];uc=cs[up]
 if uc['type']!='SLICE_LUTX':continue
 uw,ui,ut=logical(uc)
 if uw>5:continue
 inputs=[ui['I'+str(i)] for i in range(uw)];b=c['attributes']['NEXTPNR_BEL'];paired=b[:-4]+('6LUT' if b.endswith('5LUT') else '5LUT');sib=bels.get(paired)
 if sib:
  sw,sp,st=logical(cs[sib]);other=[sp['I'+str(i)] for i in range(sw)]
 else:other=[]
 union=set(inputs+other)
 if len(union)>5:continue
 for v in range(1<<uw):
  vs={bit:(v>>i)&1 for i,bit in enumerate(inputs)};assert evaluate(c,{p['I0']:evaluate(uc,vs)})==evaluate(uc,vs)
 items.append(dict(target=n,driver=up,bel=b,carry=parent,source_width=uw,source_inputs=inputs,paired_cell=sib,paired_input_union=len(union),truth_cases=1<<uw))
out=dict(passed=True,candidates=items,count=len(items),source_types=sorted(set(cs[i['driver']]['attributes']['X_ORIG_TYPE'] for i in items)),scope='Read-only one-buffer-at-a-time feasibility. Each target identity and upstream function are checked exhaustively. Shared-pin feasibility is local to the unchanged sibling; simultaneous edits require a fresh joint check. No packed edit, SAT proof, new routing, timing gain or acceptance is claimed.',sha256={str(q.resolve()):digest(q) for q in [rp,source,Path(__file__),Path(__file__).with_name('synapse32_packed_counter_encoding.py')]});a.out.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(dict(passed=True,count=len(items),source_types=out['source_types'])))
