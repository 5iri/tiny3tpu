#!/usr/bin/env python3
"""Propose moving the read-response capture FF into the final mux slice."""
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());rp=a.reference/'manifest.json';record=json.loads(rp.read_text());assert patch['passed'] and record['passed'];assert json.loads(Path(record['patch']).read_text())==patch['guard_base']
for d in [patch,record]:
 for k in ['sha256','output_sha256']:
  for n,h in d.get(k,{}).items():assert digest(n)==h,n
source=a.reference/'routed.json';cs=json.loads(source.read_text())['modules']['top']['cells'];ff=next(n for n in cs if n.endswith('$79154'));root=next(n for n in cs if '$233963.' in n and n.endswith('mux8'));site=cs[root]['attributes']['NEXTPNR_BEL'].split('/')[0];assert site=='SLICE_X114Y48';assert cs[ff]['attributes']['NEXTPNR_BEL']=='SLICE_X118Y48/DFF';assert cs[ff]['type']=='SLICE_FFX' and 'CE' not in cs[ff]['connections'];assert not any(c['type']=='SLICE_FFX' and c['attributes']['NEXTPNR_BEL'].startswith(site+'/') for c in cs.values());target=site+'/BFF';assert target not in {c['attributes']['NEXTPNR_BEL'] for c in cs.values()}|set(patch['placements'].values());new=copy.deepcopy(patch);new['placements'][ff]=target
for k in ['replacements','added_cells','added_netnames','original_cells','guard_base']:assert new[k]==patch[k]
new['rdata_placement_variant']=dict(parent=str(a.patch.resolve()),reference=str(source.resolve()),cell=ff,from_bel=cs[ff]['attributes']['NEXTPNR_BEL'],to_bel=target,execution_cycles_changed=False);new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,rp,source,Path(__file__)]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,indent=2)+'\n');print(json.dumps(new['rdata_placement_variant']))
