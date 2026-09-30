"""Distribute the common late capture condition over each eight-output OR."""
import gc
gc.disable()
import argparse,copy,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_ddr_all_capture_encoding import apply_verified as apply_base,GROUPS
from synapse32_packed_ddr_last_capture_encoding import attributes
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']

def spec(m):
 cs=m['cells'];drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for n in m['netnames'].values() for b in n['bits']}|{b for p in m['ports'].values() for b in p['bits']};fresh=max(b for b in bits if isinstance(b,int))+1;rows=[];replacements={};added={};nets={};removed={};late=[105590,105551,105571]
 for group,outputs in GROUPS.items():
  roots={drv[b]:cs[drv[b]] for b in outputs};codes=[[],[]];encoders={};decode=None
  for output in outputs:
   c=cs[drv[output]];w,p,t=logical(c);assert w==5 and [p[f'I{i}'] for i in range(2,5)]==late
   if decode is None:decode=t
   else:assert t==decode
   for i in range(2):
    codes[i].append(p[f'I{i}']);name=drv[p[f'I{i}']];encoder=cs[name];assert encoder['type']=='SLICE_LUTX' and logical(encoder)[0] in [3,5];encoders[name]=encoder
  assert len(encoders)==16 and len(set(codes[0]+codes[1]))==16
  suffix='233944' if group=='ready' else '233974';final=next(n for n in cs if '$'+suffix+'.' in n and n.endswith('.mux8'));early='$tiny3tpu$ddr_capture_or_'+suffix+'_early';w,p,t=logical(cs[early]);fw,fp,ft=logical(cs[final]);assert w==6 and fw==3 and t==(1<<64)-2 and ft==254 and fp['I0']==p['O'];assert {p[f'I{i}'] for i in range(6)}|{fp['I1'],fp['I2']}==set(outputs)
  old={**encoders,**roots,early:cs[early],final:cs[final]};oldouts={logical(c)[1]['O'] for c in old.values()};cuts=sorted({b for c in old.values() for k,b in logical(c)[1].items() if k!='O'}-oldouts);newg={};sums=[]
  for i,inputs in enumerate(codes):
   n0=f'$tiny3tpu$capture_{group}_any{i}_early';n1=f'$tiny3tpu$capture_{group}_any{i}';newg[n0]=packed(inputs[:6],fresh,(1<<64)-2);newg[n1]=packed([fresh,*inputs[6:]],fresh+1,254);nets[n0+'$net']=dict(hide_name=0,bits=[fresh],attributes={});nets[n1+'$net']=dict(hide_name=0,bits=[fresh+1],attributes={});sums.append(fresh+1);fresh+=2
  newfinal=attributes(packed([*sums,*late],fp['O'],decode),cs[final]);replacements[final]=newfinal;added.update(newg);removed.update(roots);removed[early]=cs[early];rows.append(dict(group=group,final=final,early=early,roots=roots,encoders=encoders,old=old,new={**encoders,**newg,final:newfinal},added=newg,cuts=cuts,output=fp['O']))
 assert len(removed)==18 and len(added)==8
 deadbits={b for c in removed.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
 for n,c in removed.items():assert c['type']=='SLICE_LUTX' and c['attributes']['X_ORIG_TYPE'] in ['LUT5','LUT6'] and not any(k.startswith('CONSTR_') for k in c['attributes'])
 for n,c in cs.items():
  if n in removed:continue
  c=replacements.get(n,c);assert not any(deadbits&set(bs) for bs in c['connections'].values()),('observed removed output',n);assert c['attributes'].get('CONSTR_PARENT') not in removed and not set(removed)&set(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')))
 assert not any(deadbits&set(p['bits']) for p in m['ports'].values());removednets={n:v for n,v in m['netnames'].items() if v['bits'] and set(v['bits'])<=deadbits};return dict(rows=rows,replacements=replacements,added=added,nets=nets,removed=removed,removednets=removednets)

def miters(s):
 return [emit(r['old'],r['cuts'],[r['output']],'gold')+'\n'+emit(r['new'],r['cuts'],[r['output']],'candidate')+f"\nmodule proof(input [{len(r['cuts'])-1}:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n" for r in s['rows']]

def validate(patch,prior,base):
 s=spec(base['modules']['top']);assert patch['original_cells']==prior['original_cells'];assert patch['replacements']=={**{n:c for n,c in prior['replacements'].items() if n not in s['removed']},**s['replacements']};assert patch['added_cells']=={**{n:c for n,c in prior['added_cells'].items() if n not in s['removed']},**s['added']};assert patch['added_netnames']=={**{n:v for n,v in prior['added_netnames'].items() if n not in s['removednets']},**s['nets']};assert patch['removed_cells']=={**prior['removed_cells'],**s['removed']} and patch['removed_netnames']=={**prior['removed_netnames'],**s['removednets']};assert patch['added_latency_cycles']==prior['added_latency_cycles']==0 and patch['checkpoint']==prior['checkpoint'];assert set(patch['placements'])==(set(prior['placements'])-set(s['removed']))|set(s['added'])
 for n,v in prior['placements'].items():
  if n not in s['removed']:assert patch['placements'][n]==v
 assert len(patch['or_factor_proofs'])==2
 for proof,text in zip(patch['or_factor_proofs'],miters(s)):
  assert Path(proof['miter']).read_text()==text
  for n,h in proof['sha256'].items():assert digest(n)==h,n
  assert 'SUCCESS!' in Path(proof['log']).read_text()
 m=base['modules']['top'];m['cells'].update(copy.deepcopy(s['replacements']));m['cells'].update(copy.deepcopy(s['added']));m['netnames'].update(copy.deepcopy(s['nets']))
 for n in s['removed']:del m['cells'][n]
 for n in s['removednets']:del m['netnames'][n]
 return base

def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['or_factor_base']);assert digest(bp)==patch['or_factor_base_sha256'];prior=json.loads(bp.read_text());return validate(patch,prior,apply_base(prior,design))

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_capture_or_factor',or_factor_base=str(bp),or_factor_base_sha256=digest(bp));patch['replacements'].update(s['replacements']);patch['added_cells'].update(s['added']);patch['added_netnames'].update(s['nets']);patch['removed_cells'].update(s['removed']);patch['removed_netnames'].update(s['removednets'])
 for n in s['removed']:patch['replacements'].pop(n,None);patch['added_cells'].pop(n,None);patch['placements'].pop(n,None)
 for n in s['removednets']:patch['added_netnames'].pop(n,None)
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n not in s['removed']};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')}
 import re
 def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
 for r in s['rows']:
  near=xy(placed[r['final']]['attributes']['NEXTPNR_BEL']);free=[site+'/'+l+'6LUT' for site in sites for l in 'ABCD' if site+'/'+l+'6LUT' not in occupied and site+'/'+l+'5LUT' not in occupied]
  for n in r['added']:
   bel=min(free,key=lambda b:(abs(xy(b)[0]-near[0])+abs(xy(b)[1]-near[1]),b));free.remove(bel);occupied.add(bel);patch['placements'][n]=bel
 out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';patch['or_factor_proofs']=[]
 for i,text in enumerate(miters(s)):
  v=out/f'miter-{i}.v';v.write_text(text);ys=out/f'prove-{i}.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/f'prove-{i}.log'
  with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
  patch['or_factor_proofs'].append(dict(miter=str(v),log=str(log),sha256={str(q.resolve()):digest(q) for q in [v,ys,log,tool,lib]}))
 validate(patch,prior,base);patch['sha256']=dict(prior['sha256'])
 for proof in patch['or_factor_proofs']:patch['sha256'].update(proof['sha256'])
 patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_ddr_all_capture_encoding.py'),Path(__file__).with_name('synapse32_packed_ddr_last_capture_encoding.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,primitive_sat_miters=2,removed_cells=18,added_luts=8,added_state=0,added_latency_cycles=0,cut_counts=[len(r['cuts']) for r in s['rows']])))
if __name__=='__main__':main()
