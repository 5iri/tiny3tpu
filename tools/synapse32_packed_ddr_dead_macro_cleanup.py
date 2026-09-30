"""Remove provably unobservable combinational mux children and colocate their replacements."""
import gc
gc.disable()
import argparse,copy,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_branch_predicate_ddr_combo import apply_verified as apply_base
from synapse32_packed_counter_encoding import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles']
SUFFIXES=['233945','233977','233944','233974']

def repartition(m):
 cs=m['cells'];root=next(n for n in cs if '$233974.' in n and n.endswith('.mux8'));early='$tiny3tpu$ddr_capture_or_233974_early';old={early:cs[early],root:cs[root]};w,p,t=logical(cs[early]);rw,rp,rt=logical(cs[root]);assert w==6 and rw==3 and t==(1<<64)-2 and rt==254;assert rp['I0']==p['O'];cuts=sorted({b for c in old.values() for k,b in logical(c)[1].items() if k!='O'}-{p['O']});assert len(cuts)==8
 late=[139842,139840];assert set(late)<=set(cuts);new={early:packed([b for b in cuts if b not in late],p['O'],(1<<64)-2),root:packed([p['O'],*late],rp['O'],254)}
 for n,c in new.items():
  assert not any(k.startswith('CONSTR_') for k in old[n]['attributes']);c['hide_name']=old[n]['hide_name'];c['attributes'].update({k:v for k,v in old[n]['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']})
 for word in range(256):
  values={b:(word>>i)&1 for i,b in enumerate(cuts)};a=dict(values);b=dict(values)
  for c in old.values():a[logical(c)[1]['O']]=evaluate(c,a)
  for c in new.values():b[logical(c)[1]['O']]=evaluate(c,b)
  assert a[rp['O']]==b[rp['O']]==int(word!=0)
 return root,early,old,new,cuts

def dead_set(prior,m):
 cs=m['cells'];groups={};targets=set()
 for suffix in SUFFIXES:
  root=next(n for n in cs if '$'+suffix+'.' in n and n.endswith('.mux8'));original=prior['original_cells'][root];assert original['attributes']['X_ORIG_TYPE']=='MUXF8';children=original['attributes']['CONSTR_CHILDREN'].split(';');assert len(children)==6;assert not targets&set(children);targets.update(children);groups[root]=children
 assert len(targets)==24 and not targets&set(prior['added_cells']);bits=set()
 for n in targets:
  c=cs[n];assert c['type'] in ['SLICE_LUTX','SELMUX2_1'] and c['attributes']['X_ORIG_TYPE'] in ['LUT1','LUT6','MUXF7'];assert not any(k.startswith('CONSTR_') for k in c['attributes'])
  for p,bs in c['connections'].items():
   if c['port_directions'][p]=='output':
    assert not bits&set(bs);bits.update(bs)
 for n,c in cs.items():
  if n in targets:continue
  assert not any(bits&set(bs) for bs in c['connections'].values()),('observable removed output',n)
  assert c['attributes'].get('CONSTR_PARENT') not in targets;assert not targets&set(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')))
 assert not any(bits&set(p['bits']) for p in m['ports'].values())
 nets={n:v for n,v in m['netnames'].items() if v['bits'] and set(v['bits'])<=bits}
 return groups,{n:cs[n] for n in sorted(targets)},nets

def parent(patch):
 p=Path(patch['cleanup_base_path']);assert digest(p)==patch['cleanup_base_sha256'];return json.loads(p.read_text())

def apply_verified(patch,design):
 assert patch['passed'] and patch['added_latency_cycles']==0;prior=parent(patch);base=apply_base(prior,design);m=base['modules']['top'];root,early,old,new,cuts=repartition(m);groups,removed,nets=dead_set(prior,m);assert patch['removed_cells']==removed and patch['removed_netnames']==nets and patch['cleanup_groups']==groups
 assert patch['original_cells']==prior['original_cells'] and patch['added_netnames']==prior['added_netnames'];assert set(patch['added_cells'])==set(prior['added_cells']);assert set(patch['replacements'])==set(prior['replacements'])-set(removed)
 for n,c in prior['replacements'].items():
  if n not in removed:assert patch['replacements'][n]==(new[n] if n==root else c)
 for n,c in prior['added_cells'].items():assert patch['added_cells'][n]==(new[n] if n==early else c)
 m['cells'].update(copy.deepcopy(new))
 for n in removed:del m['cells'][n]
 for n in nets:del m['netnames'][n]
 assert not set(removed)&set(patch['placements'])
 return base

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());assert prior['passed']
 rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];root,early,old,new,cuts=repartition(m);groups,removed,nets=dead_set(prior,m);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_ddr_dead_macro_cleanup',cleanup_base_path=str(bp),cleanup_base_sha256=digest(bp),removed_cells=removed,removed_netnames=nets,cleanup_groups=groups)
 patch['added_cells'][early]=new[early];patch['replacements'][root]=new[root]
 for n in removed:patch['replacements'].pop(n,None);patch['placements'].pop(n,None)
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];moves={}
 for r,children in groups.items():
  sites={placed[n]['attributes']['NEXTPNR_BEL'].split('/')[0] for n in children};assert len(sites)==1;site=sites.pop()
  if '$233945.' in r:names=['$tiny3tpu$ddr_ready_code0','$tiny3tpu$ddr_ready_code1',r]
  elif '$233977.' in r:names=['$tiny3tpu$ddr_read_valid_code0','$tiny3tpu$ddr_read_valid_code1',r]
  elif '$233944.' in r:names=['$tiny3tpu$ddr_capture_or_233944_early',r]
  else:names=['$tiny3tpu$ddr_capture_or_233974_early',r]
  occupied={patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']) for n,c in placed.items() if n not in removed and n not in names}
  free=[site+'/'+l+'6LUT' for l in 'ABCD' if site+'/'+l+'6LUT' not in occupied and site+'/'+l+'5LUT' not in occupied];assert len(free)>=len(names)
  for n,bel in zip(names,free):
   assert m['cells'][n]['type']=='SLICE_LUTX' and not any(k.startswith('CONSTR_') for k in m['cells'][n]['attributes']);patch['placements'][n]=bel;moves[n]=[placed[n]['attributes']['NEXTPNR_BEL'],bel]
 out.mkdir();v=out/'repartition.v';v.write_text(emit(old,cuts,[logical(old[root])[1]['O']],'gold')+'\n'+emit(new,cuts,[logical(new[root])[1]['O']],'candidate')+'\nmodule proof(input [7:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n');tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/'prove.log'
 with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 assert 'SUCCESS!' in log.read_text();apply_verified(patch,gold);patch['cleanup_placement_moves']=moves;patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_branch_predicate_ddr_combo.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),tool,lib,v,ys,log]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,repartition_cases=256,actual_primitive_sat=True,removed_unobservable_combinational_cells=len(removed),removed_unobservable_netnames=len(nets),colocated_cells=len(moves),added_latency_cycles=0)))
if __name__=='__main__':main()
