"""Relocate an unchanged high-fanout CPU instruction-control LUT/register pair."""
import gc
gc.disable()
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_mid_zero_flag import apply_verified as apply_base
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']
FF='$auto$ff.cc:337:slice$77219';LUT='$auto$xilinx_dffopt.cc:338:execute$269744'

def spec(m):
 cs=m['cells'];f=cs[FF];l=cs[LUT];assert f['type']=='SLICE_FFX' and f['attributes']['X_ORIG_TYPE']=='FDPE' and f['parameters']=={'INIT':'x'};assert f['connections']==dict(CK=[167701],SR=[50991],D=[197536],CE=[],Q=[51420]);assert f['attributes']['CONSTR_PARENT']==LUT and l['attributes']['CONSTR_CHILDREN']==FF and l['attributes']['X_ORIG_TYPE']=='LUT5';assert l['connections']['O6']==[197536]
 assert [n for n,c in cs.items() if c['attributes'].get('CONSTR_PARENT')==LUT]==[FF]
 return {n:cs[n] for n in [LUT,FF]}

def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['cpu_pair_base']);assert digest(bp)==patch['cpu_pair_base_sha256'];prior=json.loads(bp.read_text());base=apply_base(prior,design);assert patch['cpu_pair_cells']==spec(base['modules']['top'])
 for k in FIELDS:
  if k!='placements':assert patch[k]==prior[k]
 assert set(patch['placements'])==set(prior['placements'])|{LUT,FF}
 for n,v in prior['placements'].items():
  if n not in [LUT,FF]:assert patch['placements'][n]==v
 assert patch['placements'][LUT].endswith('6LUT') and patch['placements'][FF]==patch['placements'][LUT][:-4]+'FF'
 return base

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];cs=m['cells'];pair=spec(m);ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n not in pair};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad=set()
 for n,c in cs.items():
  if n in pair:continue
  site=placed[n]['attributes']['NEXTPNR_BEL'].split('/')[0]
  if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL')):bad.add(site)
  if c['type']=='SLICE_FFX':
   if c['attributes'].get('X_ORIG_TYPE') not in ['FDPE','FDCE'] or c['attributes'].get('X_FFSYNC','').strip()=='1' or any(c['connections'].get(p,[])!=pair[FF]['connections'][p] for p in ['CK','SR','CE']):bad.add(site)
 free=[site+'/'+l for site in sites-bad for l in 'ABCD' if all(site+'/'+l+t not in occupied for t in ['6LUT','5LUT','FF','5FF'])];assert free
 def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
 sinks=[n for n,c in cs.items() if n not in pair and any(51420 in bs for p,bs in c['connections'].items() if c['port_directions'][p]=='input')];assert len(sinks)==166;points=[xy(placed[n]['attributes']['NEXTPNR_BEL']) for n in sinks]
 def cost(b):
  x,y=xy(b);return(sum(abs(x-u)+abs(y-v) for u,v in points),b)
 chosen=min(free,key=cost);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_cpu_id_pair_placement',cpu_pair_base=str(bp),cpu_pair_base_sha256=digest(bp),cpu_pair_cells=pair);patch['placements'][LUT]=chosen+'6LUT';patch['placements'][FF]=chosen+'FF';assert chosen+'FF'!=placed[FF]['attributes']['NEXTPNR_BEL'];out.mkdir();patch['placement_evidence']=dict(sinks=len(sinks),cost_before=cost(placed[FF]['attributes']['NEXTPNR_BEL'])[0],cost_after=cost(chosen)[0],old_bel=placed[FF]['attributes']['NEXTPNR_BEL'],new_bel=chosen+'FF',criterion='minimum sum of Manhattan distance to all external Q consumers among unshared LUT/FF pairs with compatible slice controls; original FDPE INIT=x and async PRE preserved')
 # Reconstruct unchanged logic once; placement changes are independently checked after routing.
 assert patch['cpu_pair_cells']==spec(base['modules']['top'])
 patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_mid_zero_flag.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,placement=patch['placement_evidence'],logic_changed=False,added_state=0,added_latency_cycles=0)))
if __name__=='__main__':main()
