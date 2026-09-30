#!/usr/bin/env python3
"""Propose a middle placement for the long DDR write-data capture route."""
import gc
gc.disable()
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes import RecoveredHashes
p=argparse.ArgumentParser();p.add_argument('--recovery',type=Path,required=True);p.add_argument('--patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();recovery=RecoveredHashes(a.recovery);assert not a.out.exists()
patch=json.loads(a.patch.read_text());rp=a.reference/'manifest.json';record=json.loads(rp.read_text());assert patch['passed'] and record['passed']
parent=Path(record['patch']).resolve();assert str(parent) in patch['sha256'] and digest(parent)==patch['sha256'][str(parent)]
for d in [patch,record]:
 for key in ['sha256','output_sha256']:
  for n,h in d.get(key,{}).items():recovery.check(n,h)
source=a.reference/'routed.json';cs=json.loads(source.read_text())['modules']['top']['cells'];ff=next(n for n in cs if n.endswith('$68661'));root=next(n for n in cs if n.endswith('$229059'));assert cs[ff]['type']=='SLICE_FFX';assert not any(k.startswith('CONSTR_') for k in cs[ff]['attributes']);assert cs[ff]['attributes']['NEXTPNR_BEL']=='SLICE_X130Y40/C5FF';assert cs[root]['attributes']['NEXTPNR_BEL']=='SLICE_X130Y132/C6LUT'
effective={n:patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']) for n,c in cs.items()};effective.update(patch['placements']);occupied=set(effective.values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={effective[n].split('/')[0] for n,c in cs.items() if c['type'] in ['SLICE_FFX','CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'}
def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
free=[s+'/'+l+'FF' for s in sites-bad for l in 'ABCD' if s+'/'+l+'FF' not in occupied];assert free;target=min(free,key=lambda v:(abs(xy(v)[0]-130)+abs(xy(v)[1]-86),v));new=copy.deepcopy(patch);new['placements'][ff]=target
for k in patch:
 if k!='placements':assert new[k]==patch[k]
new['wdata_capture_placement_variant']=dict(parent=str(a.patch.resolve()),reference=str(source.resolve()),cell=ff,from_bel=cs[ff]['attributes']['NEXTPNR_BEL'],to_bel=target,reason='Middle placement between current data source and capture, preserving all FF parameters and connections. Destination slice has no FF/carry/mux/LUTRAM in the effective layout.',execution_cycles_changed=False)
new['placement_recovery']=recovery.metadata();new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,rp,source,Path(__file__),a.recovery,Path(__file__).with_name('synapse32_recovered_hashes.py'),Path(__file__).with_name('synapse32_rebuilt_toolchain_replay.py')]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,separators=(',',':'))+'\n');print(json.dumps(new['wdata_capture_placement_variant']))
