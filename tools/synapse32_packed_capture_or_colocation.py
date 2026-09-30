"""Remove unused timer mux children and colocate proved flags in a compatible slice."""
import gc
gc.disable()
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_capture_or_factor import apply_verified as apply_base
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']
SITE='SLICE_X120Y49'

def spec(prior,m):
 cs=m['cells'];roots=[next(n for n in prior['original_cells'] if '$'+s+'.' in n and n.endswith('.mux8')) for s in ['217671','217670']];groups={r:prior['original_cells'][r]['attributes']['CONSTR_CHILDREN'].split(';') for r in roots};targets={n for ns in groups.values() for n in ns};assert len(targets)==12 and all(len(ns)==6 for ns in groups.values()) and not targets&set(prior['removed_cells']);bits=set()
 for n in targets:
  c=cs[n];assert c['type'] in ['SLICE_LUTX','SELMUX2_1'] and c['attributes']['X_ORIG_TYPE'] in ['LUT1','LUT6','MUXF7'];assert not any(k.startswith('CONSTR_') for k in c['attributes'])
  for p,bs in c['connections'].items():
   if c['port_directions'][p]=='output':assert not bits&set(bs);bits.update(bs)
 for n,c in cs.items():
  if n in targets:continue
  assert not any(bits&set(bs) for bs in c['connections'].values()),('observable removed output',n)
  assert c['attributes'].get('CONSTR_PARENT') not in targets and not targets&set(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')))
 assert not any(bits&set(p['bits']) for p in m['ports'].values())
 nets={n:v for n,v in m['netnames'].items() if v['bits'] and set(v['bits'])<=bits};assert not set(nets)&set(prior['added_netnames'])
 moves={roots[0]:SITE+'/A6LUT',roots[1]:SITE+'/B6LUT','$tiny3tpu$timer_zero_next_early':SITE+'/C6LUT','$tiny3tpu$timer_mid_zero_next_early':SITE+'/D6LUT','$tiny3tpu$timer_zero_flag':SITE+'/AFF','$tiny3tpu$timer_mid_zero_flag':SITE+'/BFF','$tiny3tpu$capture_read_valid_any0':'SLICE_X114Y47/C6LUT','$tiny3tpu$capture_read_valid_any1':'SLICE_X114Y47/D6LUT'}
 return groups,{n:cs[n] for n in sorted(targets)},nets,moves

def validate(patch,prior,base):
 m=base['modules']['top'];groups,removed,nets,moves=spec(prior,m)
 assert patch['original_cells']==prior['original_cells'] and patch['added_cells']==prior['added_cells'] and patch['added_netnames']==prior['added_netnames']
 assert patch['replacements']=={n:c for n,c in prior['replacements'].items() if n not in removed}
 assert patch['removed_cells']=={**prior['removed_cells'],**removed} and patch['removed_netnames']=={**prior['removed_netnames'],**nets}
 assert patch['placements']=={**{n:v for n,v in prior['placements'].items() if n not in removed},**moves}
 assert patch['timer_cleanup_groups']==groups and patch['added_latency_cycles']==prior['added_latency_cycles']==0 and patch['checkpoint']==prior['checkpoint']
 # Verify the existing slice controls using the input netlist's bit namespace.
 placed_path=Path(patch['timer_cleanup_reference']);assert digest(placed_path)==patch['timer_cleanup_reference_sha256'];placed=json.loads(placed_path.read_text())['modules']['top']['cells'];others={n:c for n,c in m['cells'].items() if n not in removed and n not in moves and placed[n]['attributes']['NEXTPNR_BEL'].startswith(SITE+'/')};assert len(others)==1
 n,c=next(iter(others.items()));assert n.endswith('slice$66869') and placed[n]['attributes']['NEXTPNR_BEL']==SITE+'/DFF';assert c['type']=='SLICE_FFX' and c['attributes']['X_FFSYNC'].strip()=='1' and c['attributes']['X_ORIG_TYPE']=='FDRE' and c['connections']['CK']==[156059] and c['connections']['SR']==[138579] and c['connections']['CE']==[]
 for n in ['$tiny3tpu$timer_zero_flag','$tiny3tpu$timer_mid_zero_flag']:
  f=m['cells'][n];assert f['type']=='SLICE_FFX' and f['attributes']['X_FFSYNC'].strip()=='1' and f['attributes']['X_ORIG_TYPE']=='FDRE' and all(f['connections'][p]==c['connections'][p] for p in ['CK','SR','CE'])
 for n in removed:del m['cells'][n]
 for n in nets:del m['netnames'][n]
 return base

def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['timer_cleanup_base']);assert digest(bp)==patch['timer_cleanup_base_sha256'];prior=json.loads(bp.read_text());return validate(patch,prior,apply_base(prior,design))

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);groups,removed,nets,moves=spec(prior,base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};ref=a.reference.resolve()/'routed.json';patch.update(kind='packed_capture_or_colocation',timer_cleanup_base=str(bp),timer_cleanup_base_sha256=digest(bp),timer_cleanup_reference=str(ref),timer_cleanup_reference_sha256=digest(ref),timer_cleanup_groups=groups)
 patch['removed_cells'].update(removed);patch['removed_netnames'].update(nets)
 for n in removed:patch['replacements'].pop(n,None);patch['placements'].pop(n,None)
 patch['placements'].update(moves);validate(patch,prior,base);out.mkdir();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_capture_or_factor.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,removed_unobservable_combinational_cells=len(removed),total_removed_cells=len(patch['removed_cells']),colocated_cells=len(moves),added_state=0,added_latency_cycles=0)))
if __name__=='__main__':main()
