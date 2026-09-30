#!/usr/bin/env python3
"""Propose a bounded DMA carry-macro placement near its source registers."""
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());assert patch['passed'] and patch['joint_primitive_sat'];rp=a.reference/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and record['packed_logic_matches_patch'] and record['requested_placement_exact'];source=a.reference/'routed.json'
for d in [patch,record]:
 for key in ['sha256','output_sha256']:
  for n,h in d.get(key,{}).items():assert digest(n)==h,n
cs=json.loads(source.read_text())['modules']['top']['cells'];root=next(n for n,c in cs.items() if '$59318.' in n and c['type']=='CARRY4');moved=[root]+cs[root]['attributes']['CONSTR_CHILDREN'].split(';');assert len(moved)==9;oldsite='SLICE_X108Y135';site='SLICE_X110Y87';occupied={c['attributes']['NEXTPNR_BEL'] for c in cs.values()};new=copy.deepcopy(patch)
for n in moved:
 old=cs[n]['attributes']['NEXTPNR_BEL'];assert old.startswith(oldsite+'/');target=site+'/'+old.split('/')[1];assert target not in occupied;new['placements'][n]=target;occupied.add(target)
# Retained FF in the target uses the ordinary CFF output, not a 5FF/mux resource.
assert [(n,c['attributes']['NEXTPNR_BEL'].split('/')[1]) for n,c in cs.items() if c['attributes']['NEXTPNR_BEL'].startswith(site+'/')][0][1]=='CFF'
name=next(n for n in cs if n.endswith('$223893'));sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in cs.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'}|{site};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
target=min(free,key=lambda v:(abs(xy(v)[0]-110)+abs(xy(v)[1]-87),v));new['placements'][name]=target
for k in ['original_cells','replacements','added_cells','added_netnames','components']:assert new[k]==patch[k]
new['placement_only_variant']=dict(parent=str(a.patch.resolve()),reference=str(source.resolve()),macro=root,macro_site=site,output_lut=name,output_lut_bel=target,execution_cycles_changed=False)
new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,rp,source,Path(__file__)]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,indent=2)+'\n');print(json.dumps(new['placement_only_variant']))
