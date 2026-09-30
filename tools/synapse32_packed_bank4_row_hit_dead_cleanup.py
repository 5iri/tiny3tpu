"""Remove only the now-unobservable original bank4 row-hit comparator."""
import gc
gc.disable()
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_bank4_row_hit_late_enable_flag import apply_verified as apply_base,CONE
from synapse32_packed_timer_mid_zero_flag import FIELDS

def spec(prior,m):
 cs=m['cells'];r=json.loads(CONE.read_text());targets=set(r['combinational_cells']);assert len(targets)==27 and not targets&set(prior['removed_cells']) and not targets&set(prior['added_cells']);bits=set()
 for n in targets:
  c=cs[n];assert c['type'] in ['SLICE_LUTX','SELMUX2_1'];kind=c['attributes']['X_ORIG_TYPE'];assert kind.startswith('LUT') if c['type']=='SLICE_LUTX' else kind in ['MUXF7','MUXF8']
  par=c['attributes'].get('CONSTR_PARENT');assert not par or par in targets;assert set(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')))<=targets
  for p,bs in c['connections'].items():
   if c['port_directions'][p]=='output':assert not bits&set(bs);bits.update(bs)
 for n,c in cs.items():
  if n in targets:continue
  assert not any(bits&set(bs) for bs in c['connections'].values()),('observable removed output',n)
  assert c['attributes'].get('CONSTR_PARENT') not in targets and not targets&set(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')))
 assert not any(bits&set(p['bits']) for p in m['ports'].values())
 nets={n:v for n,v in m['netnames'].items() if v['bits'] and set(v['bits'])<=bits};return {n:cs[n] for n in sorted(targets)},nets

def validate(p,prior,base):
 m=base['modules']['top'];removed,nets=spec(prior,m)
 for k in ['original_cells','added_cells','checkpoint','added_latency_cycles']:assert p[k]==prior[k]
 assert p['added_latency_cycles']==0
 assert p['added_netnames']=={n:v for n,v in prior['added_netnames'].items() if n not in nets}
 assert p['replacements']=={n:v for n,v in prior['replacements'].items() if n not in removed}
 assert p['placements']=={n:v for n,v in prior['placements'].items() if n not in removed}
 assert p['removed_cells']=={**prior['removed_cells'],**removed} and p['removed_netnames']=={**prior['removed_netnames'],**nets}
 for n in removed:del m['cells'][n]
 for n in nets:del m['netnames'][n]
 return base

def apply_verified(p,design):
 assert p['passed'];bp=Path(p['row_cleanup_base']);assert digest(bp)==p['row_cleanup_base_sha256'];prior=json.loads(bp.read_text());return validate(p,prior,apply_base(prior,design))
def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);removed,nets=spec(prior,base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_bank4_row_hit_dead_cleanup',row_cleanup_base=str(bp),row_cleanup_base_sha256=digest(bp));patch['removed_cells'].update(removed);patch['removed_netnames'].update(nets)
 for n in removed:patch['replacements'].pop(n,None);patch['placements'].pop(n,None)
 for n in nets:patch['added_netnames'].pop(n,None)
 # Deliberately introduce observable outputs and a state cell; each must fail closed.
 m=base['modules']['top'];root=next(iter(removed));bit=next(b for p,bs in removed[root]['connections'].items() if removed[root]['port_directions'][p]=='output' for b in bs);m['ports']['negative_observer']=dict(direction='output',bits=[bit])
 try:spec(prior,m)
 except AssertionError:pass
 else:raise AssertionError('accepted output observer')
 del m['ports']['negative_observer'];original=m['cells'][root];m['cells'][root]={**original,'type':'SLICE_FFX'}
 try:spec(prior,m)
 except AssertionError:pass
 else:raise AssertionError('accepted state deletion')
 m['cells'][root]=original;m['cells']['negative_ff_observer']=dict(type='SLICE_FFX',attributes={},port_directions={'D':'input'},connections={'D':[bit]})
 try:spec(prior,m)
 except AssertionError:pass
 else:raise AssertionError('accepted register observer')
 del m['cells']['negative_ff_observer'];validate(patch,prior,base);out.mkdir();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,source,CONE,Path(__file__),Path(__file__).with_name('synapse32_packed_bank4_row_hit_late_enable_flag.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');(out/'negative-checks.json').write_text(json.dumps(dict(passed=True,top_port_observer_rejected=True,state_deletion_rejected=True,register_observer_rejected=True,sha256={str(q.resolve()):digest(q) for q in [out/'patch.json',Path(__file__)]}),indent=2)+'\n');print(json.dumps(dict(passed=True,removed_unobservable_combinational_cells=len(removed),total_removed_cells=len(patch['removed_cells']),added_state=0,added_latency_cycles=0)))
if __name__=='__main__':main()
