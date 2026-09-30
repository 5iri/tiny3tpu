#!/usr/bin/env python3
"""Place selector feedback reduction and early encoders with their relocated captures."""
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--selectors',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());rp=a.reference/'manifest.json';record=json.loads(rp.read_text());selectors=json.loads(a.selectors.read_text());assert patch['passed'] and record['passed'] and selectors['passed'];assert json.loads(Path(record['patch']).read_text())==patch['ce_base']
for d in [patch,record,selectors]:
 for k in ['sha256','output_sha256']:
  for n,h in d.get(k,{}).items():assert digest(n)==h,n
source=a.reference/'routed.json';cs=json.loads(source.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in cs.values()}|set(patch['placements'].values());sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in cs.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'6LUT' not in occupied and s+'/'+l+'5LUT' not in occupied];new=copy.deepcopy(patch);moves=[]
def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
def move(n,near):
 c=cs[n];assert c['type']=='SLICE_LUTX' and not any(k.startswith('CONSTR_') for k in c['attributes']);x,y=xy(near);target=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));assert abs(xy(target)[0]-x)+abs(xy(target)[1]-y)<=30;free.remove(target);new['placements'][n]=target;moves.append(dict(cell=n,from_bel=c['attributes']['NEXTPNR_BEL'],to_bel=target))
for suffix in ['217096','217094','217093']:move(next(n for n in cs if n.endswith('$'+suffix)),'SLICE_X118Y105')
for t in selectors['targets']:
 near=patch['placements'][t['name']]
 for n in t['added']:move(n,near)
assert len(moves)==51
for k in ['replacements','added_cells','added_netnames','original_cells','ce_base']:assert new[k]==patch[k]
new['selector_logic_placement_variant']=dict(parent=str(a.patch.resolve()),reference=str(source.resolve()),moves=moves,execution_cycles_changed=False,legality_pending=True);new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,rp,source,a.selectors,Path(__file__)]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,indent=2)+'\n');print(json.dumps(dict(moved_combinational_cells=51,logic_unchanged=True,legality_pending=True,destination_y_range=[min(xy(d['to_bel'])[1] for d in moves),max(xy(d['to_bel'])[1] for d in moves)])))
