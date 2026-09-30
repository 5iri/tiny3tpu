"""ABC-minimize only proved early cofactors; retain the late final selection."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_uart_lcr_late_choice_v2 import apply_verified,logical,evaluate,emit,discover,apply_base
from synapse32_packed_selector_patch_v4 import packed
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();prior=json.loads(a.patch.read_text());assert prior['passed']
for n,h in prior['sha256'].items():assert digest(n)==h,n
root=prior['uart_lcr_root'];late=prior['uart_lcr_bit'];cuts=[b for b in prior['uart_lcr_cuts'] if b!=late];early={n:prior['added_cells'][n] for n in prior['uart_lcr_early_cells']};fw,fp,ft=logical(prior['replacements'][root]);co=list(dict.fromkeys(fp[f'I{i}'] for i in range(fw) if fp[f'I{i}']!=late));assert 1<=len(co)<=2
out.mkdir();v=out/'early.v';v.write_text(emit(early,cuts,co,'precompute'));yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';abc=yosys.with_name('yosys-abc');ys=out/'minimize.ys';ys.write_text(f'read_verilog {lib} {v}\nsynth -top precompute -flatten -noabc\nabc -exe {abc} -lut 6\nclean\ncheck -assert\nwrite_json {out/"early.json"}\n')
with (out/'minimize.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
m=json.loads((out/'early.json').read_text())['modules']['precompute']
for n,c in list(m['cells'].items()):
 if c['type']=='$scopeinfo':
  assert not c['connections'] and not c['port_directions'];del m['cells'][n]
assert all(c['type']=='$lut' for c in m['cells'].values());assert len(m['ports']['x']['bits'])==len(cuts) and len(m['ports']['y']['bits'])==len(co)
patch=copy.deepcopy(prior);patch.pop('sha256');patch['kind']='packed_uart_lcr_abc_cofactors'
for n in prior['uart_lcr_early_cells']:
 del patch['added_cells'][n];del patch['added_netnames'][n+'$net'];del patch['placements'][n]
patch['uart_lcr_early_cells']=[];fresh=max(logical(c)[1]['O'] for c in prior['added_cells'].values())+1;bits=dict(zip(m['ports']['x']['bits'],cuts));bits.update({'0':('constant',0),'1':('constant',1)});pending=dict(m['cells'])
def make(inputs,mask):
 global fresh
 n=f'$tiny3tpu$uart_lcr_abc_early_{len(patch["uart_lcr_early_cells"])}';b=fresh;fresh+=1;patch['added_cells'][n]=packed(inputs,b,mask);patch['added_netnames'][n+'$net']=dict(hide_name=1,bits=[b],attributes={});patch['uart_lcr_early_cells'].append(n);return b
while pending:
 progressed=False
 for n,c in list(pending.items()):
  ins=c['connections']['A']
  if any(b not in bits for b in ins):continue
  mapped=[bits[b] for b in ins];variables=list(dict.fromkeys(b for b in mapped if isinstance(b,int)));table=int(c['parameters']['LUT'],2);mask=0
  for word in range(1<<len(variables)):
   vs={b:(word>>i)&1 for i,b in enumerate(variables)};index=sum((b[1] if isinstance(b,tuple) else vs[b])<<i for i,b in enumerate(mapped));mask|=((table>>index)&1)<<word
  if not variables:variables=[cuts[0]];mask=3 if mask else 0
  assert len(c['connections']['Y'])==1;ob=c['connections']['Y'][0];assert ob not in bits;bits[ob]=make(variables,mask);del pending[n];progressed=True
 assert progressed,'unresolved mapped combinational graph'
replacement=dict(zip(co,[bits[b] for b in m['ports']['y']['bits']]));replacement[late]=late;ins=list(dict.fromkeys(v for v in replacement.values() if isinstance(v,int)));mask=0
for word in range(1<<len(ins)):
 vs={b:(word>>i)&1 for i,b in enumerate(ins)};index=sum((replacement[fp[f'I{i}']][1] if isinstance(replacement[fp[f'I{i}']],tuple) else vs[replacement[fp[f'I{i}']]])<<i for i in range(fw));mask|=((ft>>index)&1)<<word
new=packed(ins,fp['O'],mask);old=prior['replacements'][root];new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k!='X_ORIG_TYPE'});patch['replacements'][root]=new
cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior['base_patch'],gold);_,_,cone,allcuts=discover(base['modules']['top']);reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
x,y=xy(patch['placements'][root])
for n in patch['uart_lcr_early_cells']:
 target=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(target);patch['placements'][n]=target
apply_verified(patch,gold);newcone={n:patch['added_cells'][n] for n in patch['uart_lcr_early_cells']};newcone[root]=new;mv=out/'miter.v';mv.write_text(emit(cone,allcuts,[fp['O']],'gold')+'\n'+emit(newcone,allcuts,[fp['O']],'candidate')+f'\nmodule proof(input [{len(allcuts)-1}:0] x,output same);wire [0:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n');proof=out/'prove.ys';proof.write_text(f'read_verilog {lib} {mv}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(proof)],stdout=f,stderr=subprocess.STDOUT,check=True)
assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,Path(__file__),v,ys,out/'minimize.log',out/'early.json',mv,proof,out/'prove.log',yosys,abc,lib]});patch['early_minimization']=dict(original_luts=len(early),mapped_luts=len(newcone)-1,late_input_preserved=late,added_latency_cycles=0);(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,**patch['early_minimization'],canonical_bdd_equivalence=True,actual_primitive_sat=True)))
