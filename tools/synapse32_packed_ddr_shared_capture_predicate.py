"""Factor all remaining DDR capture macros through two equivalent local predicates."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_mid_zero_flag import apply_verified as apply_base
from synapse32_packed_ddr_last_capture_encoding import macro,attributes
from synapse32_packed_counter_encoding import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']
GROUPS={'ready':[139456,139457,139458,139459,139460,139461,139467,139476],'read_valid':[139840,139841,139842,139843,139844,139845,139851,139860]}

def spec(m):
 cs=m['cells'];bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for n in m['netnames'].values() for b in n['bits']}|{b for p in m['ports'].values() for b in p['bits']};fresh=max(b for b in bits if isinstance(b,int))+1;drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};added={};nets={};rows=[];replacements={};late=[105590,105551,105571]
 for i,(group,outputs) in enumerate(GROUPS.items()):
  name='$tiny3tpu$capture_common_'+group;added[name]=packed(late,fresh+i,253);nets[name+'$net']=dict(hide_name=0,bits=[fresh+i],attributes={});count=0
  for output in outputs:
   root=drv[output]
   if output in [139456,139842]:assert cs[root]['attributes']['X_ORIG_TYPE']=='LUT5';continue
   assert cs[root]['attributes']['X_ORIG_TYPE']=='MUXF8';suffix=re.search(r'parse_blif\$(\d+)',root)[1];v=macro(m,suffix,fresh+2);early=[b for b in v['cuts'] if b not in late];assert len(early)==5;table={}
   for word in range(256):
    vs={b:(word>>j)&1 for j,b in enumerate(v['cuts'])};vs[241167]=0
    for c in v['old'].values():vs[logical(c)[1]['O']]=evaluate(c,vs)
    z=evaluate(added[name],vs);key=sum(vs[b]<<j for j,b in enumerate(early))|(z<<5)
    assert key not in table or table[key]==vs[output];table[key]=vs[output]
   assert set(table)==set(range(64));new=attributes(packed([*early,fresh+i],output,sum(table[j]<<j for j in range(64))),cs[root]);replacements[root]=new;rows.append(dict(group=group,common=name,root=root,old=v['old'],children=v['children'],cuts=v['cuts'],new=new));count+=1
  assert count==7
 removed={n:cs[n] for r in rows for n in r['children']};assert len(removed)==84;deadbits=set()
 for n,c in removed.items():
  assert c['type'] in ['SLICE_LUTX','SELMUX2_1'] and c['attributes']['X_ORIG_TYPE'] in ['LUT1','LUT6','MUXF7']
  for p,bs in c['connections'].items():
   if c['port_directions'][p]=='output':assert not deadbits&set(bs);deadbits.update(bs)
 for n,c in cs.items():
  if n in removed:continue
  c=replacements.get(n,c);assert not any(deadbits&set(bs) for bs in c['connections'].values()),('observable removed output',n);assert c['attributes'].get('CONSTR_PARENT') not in removed and not set(removed)&set(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')))
 assert not any(deadbits&set(p['bits']) for p in m['ports'].values());removednets={n:v for n,v in m['netnames'].items() if v['bits'] and set(v['bits'])<=deadbits}
 return dict(rows=rows,replacements=replacements,added=added,nets=nets,removed=removed,removednets=removednets)

def miters(s):
 result=[]
 for r in s['rows']:
  output=logical(r['new'])[1]['O'];result.append(emit(r['old'],[*r['cuts'],241167],[output],'gold')+'\n'+emit({r['common']:s['added'][r['common']],r['root']:r['new']},r['cuts'],[output],'candidate')+"\nmodule proof(input [7:0] x,output same);wire a,b;gold g({1'b0,x},a);candidate c(x,b);assign same=a==b;endmodule\n")
 return result

def validate(patch,prior,base,gold):
 s=spec(base['modules']['top']);original={n:gold['modules']['top']['cells'][n] for r in s['rows'] for n in r['old']};original['$PACKER_GND_DRV']=gold['modules']['top']['cells']['$PACKER_GND_DRV'];assert patch['original_cells']=={**prior['original_cells'],**original};assert patch['replacements']=={**{n:c for n,c in prior['replacements'].items() if n not in s['removed']},**s['replacements']};assert patch['added_cells']=={**prior['added_cells'],**s['added']};assert patch['added_netnames']=={**prior['added_netnames'],**s['nets']};assert not set(s['removednets'])&set(prior['added_netnames']);assert patch['removed_cells']=={**prior['removed_cells'],**s['removed']} and patch['removed_netnames']=={**prior['removed_netnames'],**s['removednets']}
 assert patch['added_latency_cycles']==prior['added_latency_cycles']==0 and patch['checkpoint']==prior['checkpoint'];changed=set(s['replacements'])|set(s['added']);assert set(patch['placements'])==(set(prior['placements'])-set(s['removed']))|changed
 for n,v in prior['placements'].items():
  if n not in s['removed'] and n not in changed:assert patch['placements'][n]==v
 assert len(patch['shared_capture_proofs'])==14
 for proof,text in zip(patch['shared_capture_proofs'],miters(s)):
  assert Path(proof['miter']).read_text()==text
  for n,h in proof['sha256'].items():assert digest(n)==h,n
  assert 'SUCCESS!' in Path(proof['log']).read_text()
 m=base['modules']['top'];m['cells'].update(copy.deepcopy(s['replacements']));m['cells'].update(copy.deepcopy(s['added']));m['netnames'].update(copy.deepcopy(s['nets']))
 for n in s['removed']:del m['cells'][n]
 for n in s['removednets']:del m['netnames'][n]
 return base

def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['shared_capture_base']);assert digest(bp)==patch['shared_capture_base_sha256'];prior=json.loads(bp.read_text());return validate(patch,prior,apply_base(prior,design),design)

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_ddr_shared_capture_predicate',shared_capture_base=str(bp),shared_capture_base_sha256=digest(bp));patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for r in s['rows'] for n in r['old']});patch['original_cells']['$PACKER_GND_DRV']=gold['modules']['top']['cells']['$PACKER_GND_DRV'];patch['replacements'].update(s['replacements']);patch['added_cells'].update(s['added']);patch['added_netnames'].update(s['nets']);patch['removed_cells'].update(s['removed']);patch['removed_netnames'].update(s['removednets'])
 for n in s['removed']:patch['replacements'].pop(n,None);patch['placements'].pop(n,None)
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n not in s['removed'] and n not in s['replacements']};sites={}
 for r in s['rows']:
  site=placed[r['root']]['attributes']['NEXTPNR_BEL'].split('/')[0];free=[site+'/'+l+'6LUT' for l in 'ABCD' if site+'/'+l+'6LUT' not in occupied and site+'/'+l+'5LUT' not in occupied];assert free;patch['placements'][r['root']]=free[0];occupied.add(free[0]);sites.setdefault(r['group'],set()).add(site)
 def xy(site):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',site).groups()))
 for group,group_sites in sites.items():
  available=[site+'/'+l+'6LUT' for site in group_sites for l in 'ABCD' if site+'/'+l+'6LUT' not in occupied and site+'/'+l+'5LUT' not in occupied];assert available
  def cost(bel):
   x,y=xy(bel);return(sum(abs(x-xy(t)[0])+abs(y-xy(t)[1]) for t in group_sites),bel)
  bel=min(available,key=cost);patch['placements']['$tiny3tpu$capture_common_'+group]=bel;occupied.add(bel)
 out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';patch['shared_capture_proofs']=[]
 for i,text in enumerate(miters(s)):
  v=out/f'miter-{i}.v';v.write_text(text);ys=out/f'prove-{i}.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/f'prove-{i}.log'
  with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
  patch['shared_capture_proofs'].append(dict(miter=str(v),log=str(log),sha256={str(q.resolve()):digest(q) for q in [v,ys,log,tool,lib]}))
 validate(patch,prior,base,gold);patch['sha256']=dict(prior['sha256'])
 for proof in patch['shared_capture_proofs']:patch['sha256'].update(proof['sha256'])
 patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_mid_zero_flag.py'),Path(__file__).with_name('synapse32_packed_ddr_last_capture_encoding.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,primitive_sat_miters=14,added_common_luts=2,replaced_mux_roots=14,removed_unobservable_cells=84,added_state=0,added_latency_cycles=0)))
if __name__=='__main__':main()
