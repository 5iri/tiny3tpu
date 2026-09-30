"""Encode two remaining critical DDR capture macros and keep their outputs on late OR inputs."""
import gc
gc.disable()
import argparse,copy,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_mid_zero_flag import apply_verified as apply_base
from synapse32_packed_counter_encoding import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']

def attributes(new,old):
 new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});return new

def macro(m,suffix,fresh):
 cs=m['cells'];root=next(n for n,c in cs.items() if '$'+suffix+'.' in n and c['attributes'].get('X_ORIG_TYPE')=='MUXF8');children=cs[root]['attributes']['CONSTR_CHILDREN'].split(';');assert len(children)==6;g=cs['$PACKER_GND_DRV'];assert g['type']=='PSEUDO_GND' and [b for p,bs in g['connections'].items() if g['port_directions'][p]=='output' for b in bs]==[241167]
 nodes={n:cs[n] for n in [root,*children]};outs={logical(c)[1]['O'] for c in nodes.values()};ins={b for c in nodes.values() for p,b in logical(c)[1].items() if p!='O'}-outs;assert 241167 in ins;cuts=sorted(ins-{241167});assert len(cuts)==8;late=[105590,105551,105571];assert set(late)<=set(cuts);early=[b for b in cuts if b not in late]
 available=set(ins);order={};pending=dict(nodes)
 while pending:
  ready=[n for n,c in pending.items() if {b for p,b in logical(c)[1].items() if p!='O'}<=available];assert ready
  for n in ready:c=pending.pop(n);order[n]=c;available.add(logical(c)[1]['O'])
 functions=[]
 for e in range(32):
  f=0
  for l in range(8):
   vs={b:(e>>i)&1 for i,b in enumerate(early)}|{b:(l>>i)&1 for i,b in enumerate(late)}|{241167:0}
   for c in order.values():vs[logical(c)[1]['O']]=evaluate(c,vs)
   f|=vs[logical(cs[root])[1]['O']]<<l
  functions.append(f)
 assert sorted(set(functions))==[0,253,255];codes={0:0,253:1,255:3};decode={0:0,1:253,2:0,3:255};added={};nets={}
 for i in range(2):
  name='$tiny3tpu$ddr_capture_'+suffix+'_code'+str(i);table=[(codes[f]>>i)&1 for f in functions];support=[j for j in range(5) if any(table[x]!=table[x^(1<<j)] for x in range(32))];mask=sum(table[sum(((x>>k)&1)<<j for k,j in enumerate(support))]<<x for x in range(1<<len(support)));added[name]=packed([early[j] for j in support],fresh+i,mask);nets[name+'$net']=dict(hide_name=0,bits=[fresh+i],attributes={})
 assert [logical(c)[0] for c in added.values()]==[5,3]
 mask=sum(((decode[word&3]>>(word>>2))&1)<<word for word in range(32));new=attributes(packed([fresh,fresh+1,*late],logical(cs[root])[1]['O'],mask),cs[root])
 for word in range(256):
  vs={b:(word>>i)&1 for i,b in enumerate(cuts)};oldv={**vs,241167:0}
  for c in order.values():oldv[logical(c)[1]['O']]=evaluate(c,oldv)
  for c in added.values():vs[logical(c)[1]['O']]=evaluate(c,vs)
  assert evaluate(new,vs)==oldv[logical(cs[root])[1]['O']]
 return dict(root=root,children=children,old=order,cuts=cuts,new=new,added=added,nets=nets)

def repartition(m,suffix,late):
 cs=m['cells'];root=next(n for n in cs if '$'+suffix+'.' in n and n.endswith('.mux8'));early='$tiny3tpu$ddr_capture_or_'+suffix+'_early';old={early:cs[early],root:cs[root]};w,p,t=logical(cs[early]);rw,rp,rt=logical(cs[root]);assert w==6 and rw==3 and t==(1<<64)-2 and rt==254 and rp['I0']==p['O'];cuts=sorted({b for c in old.values() for k,b in logical(c)[1].items() if k!='O'}-{p['O']});assert len(cuts)==8 and len(late)==3 and len(set(late))==3 and set(late)<=set(cuts)
 new={early:attributes(packed([b for b in cuts if b not in late],p['O'],(1<<32)-2),cs[early]),root:attributes(packed([p['O'],*late],rp['O'],(1<<16)-2),cs[root])}
 for word in range(256):
  vs={b:(word>>i)&1 for i,b in enumerate(cuts)};ov=dict(vs);nv=dict(vs)
  for c in old.values():ov[logical(c)[1]['O']]=evaluate(c,ov)
  for c in new.values():nv[logical(c)[1]['O']]=evaluate(c,nv)
  assert ov[rp['O']]==nv[rp['O']]==int(word!=0)
 return dict(root=root,early=early,old=old,new=new,cuts=cuts)

def spec(m):
 cs=m['cells'];bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']};fresh=max(b for b in bits if isinstance(b,int))+1;macros=[macro(m,suffix,fresh+2*i) for i,suffix in enumerate(['233980','233951'])];ors=[repartition(m,'233974',[139845,139842,139840]),repartition(m,'233944',[139467,139456,139457])];replacements={s['root']:s['new'] for s in macros};added={n:c for s in macros for n,c in s['added'].items()};nets={n:v for s in macros for n,v in s['nets'].items()}
 for s in ors:replacements[s['root']]=s['new'][s['root']];added[s['early']]=s['new'][s['early']]
 targets={n for s in macros for n in s['children']};assert len(targets)==12;deadbits={b for n in targets for p,bs in cs[n]['connections'].items() if cs[n]['port_directions'][p]=='output' for b in bs}
 for n in targets:
  c=cs[n];assert c['type'] in ['SLICE_LUTX','SELMUX2_1'] and c['attributes']['X_ORIG_TYPE'] in ['LUT1','LUT6','MUXF7']
 for n,c in cs.items():
  if n in targets:continue
  c=replacements.get(n,added.get(n,c));assert not any(deadbits&set(bs) for bs in c['connections'].values()),('observable removed output',n);assert c['attributes'].get('CONSTR_PARENT') not in targets and not targets&set(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')))
 assert not any(deadbits&set(p['bits']) for p in m['ports'].values());removednets={n:v for n,v in m['netnames'].items() if v['bits'] and set(v['bits'])<=deadbits};removed={n:cs[n] for n in sorted(targets)}
 return dict(macros=macros,ors=ors,replacements=replacements,added=added,nets=nets,removed=removed,removednets=removednets)

def miters(s):
 texts=[]
 for v in s['macros']:
  out=logical(v['old'][v['root']])[1]['O'];texts.append(emit(v['old'],[*v['cuts'],241167],[out],'gold')+'\n'+emit({**v['added'],v['root']:v['new']},v['cuts'],[out],'candidate')+"\nmodule proof(input [7:0] x,output same);wire a,b;gold g({1'b0,x},a);candidate c(x,b);assign same=a==b;endmodule\n")
 for v in s['ors']:
  out=logical(v['old'][v['root']])[1]['O'];texts.append(emit(v['old'],v['cuts'],[out],'gold')+'\n'+emit(v['new'],v['cuts'],[out],'candidate')+'\nmodule proof(input [7:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
 return texts

def validate(patch,prior,base,gold):
 m=base['modules']['top'];s=spec(m);original={n:gold['modules']['top']['cells'][n] for v in s['macros'] for n in v['old']};original['$PACKER_GND_DRV']=gold['modules']['top']['cells']['$PACKER_GND_DRV'];assert patch['original_cells']=={**prior['original_cells'],**original};assert patch['replacements']=={**{n:c for n,c in prior['replacements'].items() if n not in s['removed']},**s['replacements']};assert patch['added_cells']=={**prior['added_cells'],**s['added']};assert patch['added_netnames']=={**prior['added_netnames'],**s['nets']};assert not set(s['removednets'])&set(prior['added_netnames']);assert patch['removed_cells']=={**prior['removed_cells'],**s['removed']} and patch['removed_netnames']=={**prior['removed_netnames'],**s['removednets']}
 assert patch['added_latency_cycles']==prior['added_latency_cycles']==0 and patch['checkpoint']==prior['checkpoint'];newnames={v['root'] for v in s['macros']}|{n for v in s['macros'] for n in v['added']};assert set(patch['placements'])==(set(prior['placements'])-set(s['removed']))|newnames
 for n,v in prior['placements'].items():
  if n not in s['removed'] and n not in newnames:assert patch['placements'][n]==v
 assert len(patch['capture_proofs'])==4
 for proof,text in zip(patch['capture_proofs'],miters(s)):
  assert Path(proof['miter']).read_text()==text
  for n,h in proof['sha256'].items():assert digest(n)==h,n
  assert 'SUCCESS!' in Path(proof['log']).read_text()
 m['cells'].update(copy.deepcopy(s['replacements']));m['cells'].update(copy.deepcopy(s['added']));m['netnames'].update(copy.deepcopy(s['nets']))
 for n in s['removed']:del m['cells'][n]
 for n in s['removednets']:del m['netnames'][n]
 return base

def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['capture_base']);assert digest(bp)==patch['capture_base_sha256'];prior=json.loads(bp.read_text());return validate(patch,prior,apply_base(prior,design),design)

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_ddr_last_capture_encoding',capture_base=str(bp),capture_base_sha256=digest(bp));patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for v in s['macros'] for n in v['old']});patch['original_cells']['$PACKER_GND_DRV']=gold['modules']['top']['cells']['$PACKER_GND_DRV'];patch['replacements'].update(s['replacements']);patch['added_cells'].update(s['added']);patch['added_netnames'].update(s['nets']);patch['removed_cells'].update(s['removed']);patch['removed_netnames'].update(s['removednets'])
 for n in s['removed']:patch['replacements'].pop(n,None);patch['placements'].pop(n,None)
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells']
 for v in s['macros']:
  site=placed[v['root']]['attributes']['NEXTPNR_BEL'].split('/')[0];names=[v['root'],*v['added']];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n not in s['removed'] and n not in names};free=[site+'/'+l+'6LUT' for l in 'ABCD' if site+'/'+l+'6LUT' not in occupied and site+'/'+l+'5LUT' not in occupied];assert len(free)>=3
  for n,bel in zip(names,free):patch['placements'][n]=bel
 out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';patch['capture_proofs']=[]
 for i,text in enumerate(miters(s)):
  v=out/f'miter-{i}.v';v.write_text(text);ys=out/f'prove-{i}.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/f'prove-{i}.log'
  with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
  patch['capture_proofs'].append(dict(miter=str(v),log=str(log),sha256={str(q.resolve()):digest(q) for q in [v,ys,log,tool,lib]}))
 validate(patch,prior,base,gold);patch['sha256']=dict(prior['sha256'])
 for proof in patch['capture_proofs']:patch['sha256'].update(proof['sha256'])
 patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_mid_zero_flag.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,macro_cases=512,or_cases=512,actual_primitive_sat_miters=4,added_luts=4,removed_unobservable_combinational_cells=12,added_state=0,added_latency_cycles=0)))
if __name__=='__main__':main()
