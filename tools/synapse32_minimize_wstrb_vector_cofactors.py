"""Minimize shared early terms of the proved four-output strobe rewrite."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_wstrb_vector_choice import apply_verified,apply_base,discover,logical,emit
from synapse32_packed_selector_patch_v4 import packed
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();prior=json.loads(a.patch.read_text());assert prior['passed']
for n,h in prior['sha256'].items():assert digest(n)==h,n
roots=prior['wstrb_vector_roots'];late=prior['wstrb_vector_late'];cuts=[b for b in prior['wstrb_vector_cuts'] if b!=late];early={n:prior['added_cells'][n] for n in prior['wstrb_vector_early']};co=list(dict.fromkeys(v for root in roots for k,v in logical(prior['replacements'][root])[1].items() if k!='O' and v!=late));assert co
out.mkdir();v=out/'early.v';v.write_text(emit(early,cuts,co,'precompute'));yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');abc=yosys.with_name('yosys-abc');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'minimize.ys';ys.write_text(f'read_verilog {lib} {v}\nsynth -top precompute -flatten -noabc\nabc -exe {abc} -lut 6\nclean\ncheck -assert\nwrite_json {out/"early.json"}\n')
with (out/'minimize.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
m=json.loads((out/'early.json').read_text())['modules']['precompute']
for n,c in list(m['cells'].items()):
 if c['type']=='$scopeinfo':assert not c['connections'] and not c['port_directions'];del m['cells'][n]
assert all(c['type']=='$lut' for c in m['cells'].values());assert len(m['ports']['x']['bits'])==len(cuts) and len(m['ports']['y']['bits'])==len(co)
patch=copy.deepcopy(prior);patch.pop('sha256');patch['kind']='packed_wstrb_vector_abc'
for n in prior['wstrb_vector_early']:del patch['added_cells'][n];del patch['added_netnames'][n+'$net'];del patch['placements'][n]
patch['wstrb_vector_early']=[];fresh=max(logical(c)[1]['O'] for c in prior['added_cells'].values())+1;bits=dict(zip(m['ports']['x']['bits'],cuts));bits.update({'0':('constant',0),'1':('constant',1)});pending=dict(m['cells'])
def make(ins,mask):
 global fresh
 n=f'$tiny3tpu$wstrb_vector_abc_early_{len(patch["wstrb_vector_early"])}';b=fresh;fresh+=1;patch['added_cells'][n]=packed(ins,b,mask);patch['added_netnames'][n+'$net']=dict(hide_name=1,bits=[b],attributes={});patch['wstrb_vector_early'].append(n);return b
while pending:
 progress=False
 for n,c in list(pending.items()):
  if any(b not in bits for b in c['connections']['A']):continue
  mapped=[bits[b] for b in c['connections']['A']];ins=list(dict.fromkeys(b for b in mapped if isinstance(b,int)));mask=0;truth=int(c['parameters']['LUT'],2)
  for word in range(1<<len(ins)):
   vs={b:(word>>i)&1 for i,b in enumerate(ins)};index=sum((b[1] if isinstance(b,tuple) else vs[b])<<i for i,b in enumerate(mapped));mask|=((truth>>index)&1)<<word
  if not ins:ins=[cuts[0]];mask=3 if mask else 0
  assert len(c['connections']['Y'])==1;ob=c['connections']['Y'][0];assert ob not in bits;bits[ob]=make(ins,mask);del pending[n];progress=True
 assert progress,'unresolved early mapped DAG'
remap=dict(zip(co,[bits[b] for b in m['ports']['y']['bits']]));remap[late]=late
for root in roots:
 w,ports,truth=logical(prior['replacements'][root]);mapped=[remap[ports[f'I{i}']] for i in range(w)];ins=list(dict.fromkeys(b for b in mapped if isinstance(b,int)));mask=0
 for word in range(1<<len(ins)):
  vs={b:(word>>i)&1 for i,b in enumerate(ins)};index=sum((b[1] if isinstance(b,tuple) else vs[b])<<i for i,b in enumerate(mapped));mask|=((truth>>index)&1)<<word
 if not ins:ins=[late];mask=3 if mask else 0
 new=packed(ins,ports['O'],mask);old=prior['replacements'][root];new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k!='X_ORIG_TYPE'});patch['replacements'][root]=new
cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior['wstrb_vector_base'],gold);actual_roots,_,cone,allcuts=discover(base['modules']['top']);assert actual_roots==roots;reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
x,y=xy(patch['placements'][roots[0]])
for n in patch['wstrb_vector_early']:
 b=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(b);patch['placements'][n]=b
apply_verified(patch,gold);newcone={n:patch['added_cells'][n] for n in patch['wstrb_vector_early']};newcone.update({r:patch['replacements'][r] for r in roots});outs=[logical(base['modules']['top']['cells'][r])[1]['O'] for r in roots];mv=out/'miter.v';mv.write_text(emit(cone,allcuts,outs,'gold')+'\n'+emit(newcone,allcuts,outs,'candidate')+f'\nmodule proof(input [{len(allcuts)-1}:0] x,output same);wire [3:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n');proof=out/'prove.ys';proof.write_text(f'read_verilog {lib} {mv}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(proof)],stdout=f,stderr=subprocess.STDOUT,check=True)
assert 'SUCCESS!' in (out/'prove.log').read_text();patch['early_minimization']=dict(original_luts=len(early),mapped_luts=len(patch['wstrb_vector_early']),late_input_preserved=late,outputs=4,added_latency_cycles=0);patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,Path(__file__),v,ys,out/'minimize.log',out/'early.json',mv,proof,out/'prove.log',yosys,abc,lib]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,**patch['early_minimization'],canonical_bdd_equivalence=True,actual_primitive_sat=True)))
