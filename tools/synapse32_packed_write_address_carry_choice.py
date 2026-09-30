"""Use two proved early address-comparison cofactors and one late carry-select LUT."""
import gc
gc.disable()
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_joint_carry_buffer_inline import apply_verified as apply_base
from synapse32_packed_timer_mid_zero_flag import FIELDS
from synapse32_packed_counter_encoding import logical,emit
FEAS=Path('build-grade2-write-address-carry-abc-feasibility-v2/manifest.json').resolve()
def spec(m):
 f=json.loads(FEAS.read_text());assert f['passed'] and f['actual_primitive_sat'] and f['late_carry_absent_from_early_cofactors'];cs=m['cells']
 for n,h in f['sha256'].items():assert digest(n)==h,n
 def functional(c):
  c=copy.deepcopy(c);c['attributes']={k:v for k,v in c['attributes'].items() if k not in ['BEL_STRENGTH','NEXTPNR_BEL']};return c
 assert all(functional(cs[n])==functional(c) for n,c in {**f['old_cone'],**f['constant_drivers']}.items());old={n:cs[n] for n in f['old_cone']};added=copy.deepcopy(f['prospective_added']);root=f['root'];final=copy.deepcopy(f['prospective_final']);final['hide_name']=cs[root]['hide_name'];final['attributes'].update({k:v for k,v in cs[root]['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});assert len(added)==49
 allbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for n in m['netnames'].values() for b in n['bits']}|{b for p in m['ports'].values() for b in p['bits']};outs=[logical(c)[1]['O'] for c in added.values()];assert len(outs)==len(set(outs)) and not set(outs)&allbits and not set(added)&set(cs)
 available=set(f['early_cuts'])
 for c in added.values():
  w,p,t=logical(c);assert {p['I'+str(i)] for i in range(w)}<=available and f['late_carry'] not in p.values();available.add(p['O'])
 _,p,t=logical(final);assert p['I2']==f['late_carry'] and t==202 and p['O']==f['output']
 children=cs[root]['attributes']['CONSTR_CHILDREN'].split(';');assert len(children)==2;removed={n:cs[n] for n in children};deadbits={logical(c)[1]['O'] for c in removed.values()}
 for n,c in removed.items():assert c['type']=='SLICE_LUTX' and c['attributes']['CONSTR_PARENT']==root
 for n,c in {**cs,**added,root:final}.items():
  if n in removed:continue
  assert not any(deadbits&set(bs) for bs in c['connections'].values()),('observable removed output',n);assert c['attributes'].get('CONSTR_PARENT') not in removed and not set(removed)&set(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')))
 assert not any(deadbits&set(p['bits']) for p in m['ports'].values());removednets={n:v for n,v in m['netnames'].items() if v['bits'] and set(v['bits'])<=deadbits};nets={n+'$net':dict(hide_name=0,bits=[logical(c)[1]['O']],attributes={}) for n,c in added.items()};assert not set(nets)&set(m['netnames'])
 constants={b:int(c['type']=='PSEUDO_VCC') for c in f['constant_drivers'].values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};leaves=f['cuts'];external=[b for b in leaves if b not in constants];pos={b:i for i,b in enumerate(external)};bus='{'+','.join("1'b"+str(constants[b]) if b in constants else f'x[{pos[b]}]' for b in reversed(leaves))+'}';text=emit(old,leaves,[f['output']],'gold')+'\n'+emit({**added,root:final},leaves,[f['output']],'gate')+f'\nmodule proof(input [{len(external)-1}:0] x,output same);wire a,b;gold g({bus},a);gate t({bus},b);assign same=a==b;endmodule\n';assert (FEAS.parent/'miter.v').read_text()==text and 'SAT proof finished - no model found: SUCCESS!' in (FEAS.parent/'prove.log').read_text()
 return f,old,added,final,nets,removed,removednets

def validate(p,prior,base,gold):
 m=base['modules']['top'];f,old,added,final,nets,removed,removednets=spec(m);root=f['root'];assert p['carry_choice_feasibility']==str(FEAS) and p['carry_choice_feasibility_sha256']==digest(FEAS)
 original=gold['modules']['top']['cells'];expected={n:original[n] for n in {*old,*f['constant_drivers']} if n in original};assert p['original_cells']=={**prior['original_cells'],**expected};assert p['replacements']=={**{n:c for n,c in prior['replacements'].items() if n not in removed},root:final};assert not set(added)&set(prior['added_cells']);assert p['added_cells']=={**prior['added_cells'],**added};assert p['added_netnames']=={**prior['added_netnames'],**nets};assert not set(removednets)&set(prior['added_netnames']);assert p['removed_cells']=={**prior['removed_cells'],**removed} and p['removed_netnames']=={**prior['removed_netnames'],**removednets};assert p['checkpoint']==prior['checkpoint'] and p['added_latency_cycles']==prior['added_latency_cycles']==0
 assert set(p['placements'])==(set(prior['placements'])-set(removed))|set(added)|{root}
 for n,b in prior['placements'].items():
  if n not in removed and n!=root:assert p['placements'][n]==b
 assert all(p['placements'][n].endswith('6LUT') for n in [*added,root]);m['cells'].update(copy.deepcopy(added));m['cells'][root]=copy.deepcopy(final);m['netnames'].update(copy.deepcopy(nets))
 for n in removed:del m['cells'][n]
 for n in removednets:del m['netnames'][n]
 return base

def apply_verified(p,design):
 bp=Path(p['carry_choice_base']);assert p['passed'] and digest(bp)==p['carry_choice_base_sha256'];prior=json.loads(bp.read_text());return validate(p,prior,apply_base(prior,design),design)
def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';r=json.loads(rp.read_text());assert r['passed'] and Path(r['patch'])==bp
 for d in [prior,r]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);f,old,added,final,nets,removed,removednets=spec(base['modules']['top']);root=f['root'];patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_write_address_late_carry_choice',carry_choice_base=str(bp),carry_choice_base_sha256=digest(bp),carry_choice_feasibility=str(FEAS),carry_choice_feasibility_sha256=digest(FEAS));original=gold['modules']['top']['cells'];patch['original_cells'].update({n:original[n] for n in {*old,*f['constant_drivers']} if n in original});patch['replacements'][root]=final;patch['added_cells'].update(added);patch['added_netnames'].update(nets);patch['removed_cells'].update(removed);patch['removed_netnames'].update(removednets)
 for n in removed:patch['replacements'].pop(n,None);patch['placements'].pop(n,None)
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n not in removed and n!=root};site=placed[root]['attributes']['NEXTPNR_BEL'].split('/')[0];free_root=[site+'/'+l+'6LUT' for l in 'ABCD' if all(site+'/'+l+t not in occupied for t in ['5LUT','6LUT'])];assert free_root;patch['placements'][root]=free_root[0];occupied.add(free_root[0]);sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for n,c in placed.items() if n not in removed and n!=root and (c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL')))}
 def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
 center=xy(patch['placements'][root]);cs=base['modules']['top']['cells'];drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};locations={b:xy(placed[n]['attributes']['NEXTPNR_BEL']) for b,n in drv.items() if placed[n]['attributes']['NEXTPNR_BEL'].startswith('SLICE_')}
 for n,c in added.items():
  w,p,t=logical(c);points=[locations[p['I'+str(i)]] for i in range(w)]+[center,center];target=tuple(sorted(p[i] for p in points)[len(points)//2] for i in range(2));free=[site+'/'+l+'6LUT' for site in sites-bad for l in 'ABCD' if all(site+'/'+l+t not in occupied for t in ['5LUT','6LUT'])];assert free;bel=min(free,key=lambda b:(sum(abs(a-b) for a,b in zip(xy(b),target)),b));patch['placements'][n]=bel;occupied.add(bel);locations[p['O']]=xy(bel)
 validate(patch,prior,base,gold);out.mkdir();patch['sha256']=dict(prior['sha256']);patch['sha256'].update(f['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,FEAS,Path(__file__),Path(__file__).with_name('synapse32_packed_joint_carry_buffer_inline.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,added_luts=49,removed_unobservable_cells=2,added_state=0,added_latency_cycles=0,late_carry_final_lut_only=True)))
if __name__=='__main__':main()
