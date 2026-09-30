"""Move only the long DDR capture's source LUT to a middle free LUT site."""
import gc
gc.disable()
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes import RecoveredHashes
p=argparse.ArgumentParser();p.add_argument('--recovery',type=Path,required=True);p.add_argument('--patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();recovery=RecoveredHashes(a.recovery);assert not a.out.exists();patch=json.loads(a.patch.read_text());rp=a.reference/'manifest.json';record=json.loads(rp.read_text());assert patch['passed'] and record['passed'] and Path(record['patch']).resolve()==a.patch.resolve()
for d in [patch,record]:
 for k in ['sha256','output_sha256']:
  for n,h in d.get(k,{}).items():recovery.check(n,h)
source=a.reference/'routed.json';cs=json.loads(source.read_text())['modules']['top']['cells'];root=next(n for n in cs if n.endswith('$229059'));ff=next(n for n in cs if n.endswith('$68661'));assert cs[root]['type']=='SLICE_LUTX' and cs[root]['attributes']['X_ORIG_TYPE']=='LUT3';assert 'CONSTR_PARENT' not in cs[root]['attributes'];assert cs[root]['attributes']['NEXTPNR_BEL']=='SLICE_X130Y132/C6LUT' and cs[ff]['attributes']['NEXTPNR_BEL']=='SLICE_X130Y40/C5FF'
children=list(filter(None,cs[root]['attributes'].get('CONSTR_CHILDREN','').split(';')));assert len(children)==1;child=children[0];assert child.endswith('$68091') and cs[child]['type']=='SLICE_FFX' and cs[child]['attributes']['CONSTR_PARENT']==root and cs[child]['attributes']['NEXTPNR_BEL']=='SLICE_X130Y132/CFF'
effective={n:patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']) for n,c in cs.items()};occupied=set(effective.values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={effective[n].split('/')[0] for n,c in cs.items() if c['type'] in ['SLICE_FFX','CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied and s+'/'+l+'FF' not in occupied]
def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
target=min(free,key=lambda v:(abs(xy(v)[0]-130)+abs(xy(v)[1]-86),v));new=copy.deepcopy(patch);new['placements'][root]=target;new['placements'][child]=target.replace('6LUT','FF')
for k in patch:
 if k!='placements':assert new[k]==patch[k]
new['wdata_source_placement_variant']=dict(parent=str(a.patch.resolve()),reference=str(source.resolve()),cell=root,from_bel=effective[root],to_bel=target,paired_ff=child,paired_ff_from=effective[child],paired_ff_to=new['placements'][child],reason='Middle placement for source LUT and its one constrained FF child; macro geometry and all logic preserved. Other capture FFs remain fixed.',execution_cycles_changed=False);new['placement_recovery']=recovery.metadata();new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,rp,source,Path(__file__),a.recovery,Path(__file__).with_name('synapse32_recovered_hashes.py'),Path(__file__).with_name('synapse32_rebuilt_toolchain_replay.py')]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,separators=(',',':'))+'\n');print(json.dumps(new['wdata_source_placement_variant']))
