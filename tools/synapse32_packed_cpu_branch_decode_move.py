"""Relocate seven unchanged branch decode LUTs between control and jump logic."""
import gc
gc.disable()
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_mid_zero_flag import apply_verified as apply_base,FIELDS
NAMES=[f'$tiny3tpu$branch_pair_{i}' for i in range(3)]+[f'$tiny3tpu$branch_condition_{i}' for i in range(3)]+['$abc$216920$auto$blifparse.cc:557:parse_blif$220968']
def spec(m):
 cells={n:m['cells'][n] for n in NAMES}
 for n,c in cells.items():
  assert c['type']=='SLICE_LUTX' and c['attributes']['X_ORIG_TYPE'].startswith('LUT')
  assert not any(k.startswith('CONSTR_') for k in c['attributes']),n
 return cells
def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['decode_base']);assert digest(bp)==patch['decode_base_sha256'];prior=json.loads(bp.read_text());base=apply_base(prior,design);assert patch['decode_cells']==spec(base['modules']['top'])
 for k in FIELDS:
  if k!='placements':assert patch[k]==prior[k]
 assert set(patch['placements'])==set(prior['placements'])|set(NAMES)
 for n,v in prior['placements'].items():
  if n not in NAMES:assert patch['placements'][n]==v
 assert all(patch['placements'][n].endswith('6LUT') for n in NAMES)
 return base

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];cs=m['cells'];selected=spec(m);ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n not in selected};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL'))}
 def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
 patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_cpu_branch_decode_placement',decode_base=str(bp),decode_base_sha256=digest(bp),decode_cells=selected)
 for n in NAMES:
  free=[site+'/'+l+'6LUT' for site in sites-bad for l in 'ABCD' if all(site+'/'+l+t not in occupied for t in ['6LUT','5LUT'])];assert free
  chosen=min(free,key=lambda b:(abs(xy(b)[0]-97)+abs(xy(b)[1]-35),b));patch['placements'][n]=chosen;occupied.add(chosen)
 out.mkdir();patch['placement_evidence']={n:dict(old=placed[n]['attributes']['NEXTPNR_BEL'],new=patch['placements'][n]) for n in NAMES};patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_mid_zero_flag.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,placement=patch['placement_evidence'],logic_changed=False,added_state=0,added_latency_cycles=0)))
if __name__=='__main__':main()
