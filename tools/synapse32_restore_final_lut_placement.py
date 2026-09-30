"""Retain a rewritten final LUT in its original, unshared 6-LUT BEL."""
import gc
gc.disable()
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes import RecoveredHashes
p=argparse.ArgumentParser();p.add_argument('--recovery',type=Path,required=True);p.add_argument('--patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--root-field',choices=['uart_lcr_root','ar_encoding_root'],required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();recovery=RecoveredHashes(a.recovery);patch=json.loads(a.patch.read_text());rp=a.reference/'manifest.json';record=json.loads(rp.read_text());assert patch['passed'] and record['passed']
for d in [patch,record]:
 for k in ['sha256','output_sha256']:
  for n,h in d.get(k,{}).items():recovery.check(n,h)
source=a.reference/'routed.json';cs=json.loads(source.read_text())['modules']['top']['cells'];root=patch[a.root_field];old=cs[root];assert old['type']=='SLICE_LUTX' and not any(k.startswith('CONSTR_') for k in old['attributes']);target=old['attributes']['NEXTPNR_BEL'];assert target.endswith('6LUT');sibling=target.removesuffix('6LUT')+'5LUT';occupied={patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']) for n,c in cs.items() if n!=root}|{v for n,v in patch['placements'].items() if n!=root};assert target not in occupied and sibling not in occupied
new=copy.deepcopy(patch);new['placements'][root]=target
for k in patch:
 if k!='placements':assert new[k]==patch[k]
new['final_lut_original_placement']=dict(parent=str(a.patch.resolve()),cell=root,from_bel=patch['placements'][root],to_bel=target,unshared_5lut_bel=sibling,logic_unchanged=True,added_latency_cycles=0);new['placement_recovery']=recovery.metadata();new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,rp,source,a.recovery,Path(__file__),Path(__file__).with_name('synapse32_recovered_hashes.py'),Path(__file__).with_name('synapse32_rebuilt_toolchain_replay.py')]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,separators=(',',':'))+'\n');print(json.dumps(new['final_lut_original_placement']))
