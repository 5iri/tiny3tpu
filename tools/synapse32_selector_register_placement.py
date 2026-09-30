#!/usr/bin/env python3
"""Move selector capture registers and final LUTs toward their late control sources."""
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--selectors',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());rp=a.reference/'manifest.json';record=json.loads(rp.read_text());selectors=json.loads(a.selectors.read_text());assert patch['passed'] and record['passed'] and selectors['passed'];assert json.loads(Path(record['patch']).read_text())==patch
for d in [patch,record,selectors]:
 for k in ['sha256','output_sha256']:
  for n,h in d.get(k,{}).items():assert digest(n)==h,n
source=a.reference/'routed.json';cs=json.loads(source.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in cs.values()};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in cs.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};ffsites={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in cs.values() if c['type']=='SLICE_FFX'};free=[(s,l) for s in sites-bad-ffsites for l in 'ABCD' if s+'/'+l+'6LUT' not in occupied and s+'/'+l+'5LUT' not in occupied and s+'/'+l+'FF' not in occupied and s+'/'+l+'5FF' not in occupied]
def xy(s):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',s).groups()))
def control(c):return ({k:v for k,v in c['connections'].items() if k not in ['D','Q']},{k:v for k,v in c['parameters'].items() if 'INVERTED' in k},{k:v for k,v in c['attributes'].items() if k in ['X_FF_AS_LATCH','X_FFSYNC']})
new=copy.deepcopy(patch);moves=[];signature=None
for t in selectors['targets']:
 root=t['name'];c=cs[root];assert c['type']=='SLICE_LUTX';outbit=c['connections']['O6'][0];ffs=[n for n,c in cs.items() if c['type']=='SLICE_FFX' and c['connections'].get('D')==[outbit]];assert len(ffs)==1;ff=ffs[0];fc=cs[ff]
 if signature is None:signature=control(fc)
 assert control(fc)==signature
 assert not any(k.startswith('CONSTR_') for k in fc['attributes'])
 s,l=min(free,key=lambda v:(abs(xy(v[0])[0]-115)+abs(xy(v[0])[1]-105),v));free.remove((s,l));assert abs(xy(s)[0]-115)+abs(xy(s)[1]-105)<=30
 new['placements'][root]=s+'/'+l+'6LUT';new['placements'][ff]=s+'/'+l+'FF';moves.append(dict(root=root,ff=ff,root_from=c['attributes']['NEXTPNR_BEL'],ff_from=fc['attributes']['NEXTPNR_BEL'],root_to=new['placements'][root],ff_to=new['placements'][ff]))
assert len(moves)==16;assert len({v for d in moves for v in [d['root_to'],d['ff_to']]})==32
for k in ['replacements','added_cells','added_netnames','original_cells','guard_base']:assert new[k]==patch[k]
new['selector_placement_variant']=dict(parent=str(a.patch.resolve()),reference=str(source.resolve()),moves=moves,shared_register_controls=signature,execution_cycles_changed=False,legality_pending=True);new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,rp,source,a.selectors,Path(__file__)]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,indent=2)+'\n');print(json.dumps(dict(selector_pairs=len(moves),sites=sorted({d['ff_to'].split('/')[0] for d in moves}),logic_unchanged=True,legality_pending=True)))
