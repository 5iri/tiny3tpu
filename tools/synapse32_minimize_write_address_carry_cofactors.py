"""Map the proved early write-address cofactors to LUT6s, retaining a one-LUT late path."""
import argparse,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
p=argparse.ArgumentParser();p.add_argument('--feasibility',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();prior=json.loads(a.feasibility.read_text());assert prior['passed'];out=a.out.resolve();assert not out.exists()
for n,h in prior['sha256'].items():assert digest(n)==h,n
late=prior['late_carry'];early=prior['early_cuts'];root=prior['root'];_,fp,ft=logical(prior['prospective_final']);assert ft==202 and fp['I2']==late;co=[fp['I0'],fp['I1']];assert len(set(co))==2;out.mkdir();v=out/'early.v';v.write_text(emit(prior['prospective_added'],early,co,'precompute'));tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');abc=tool.with_name('yosys-abc');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'minimize.ys';ys.write_text(f'read_verilog {lib} {v}\nsynth -top precompute -flatten -noabc\nabc -exe {abc} -lut 6\nclean\ncheck -assert\nwrite_json {out/"early.json"}\n');log=out/'minimize.log'
with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
m=json.loads((out/'early.json').read_text())['modules']['precompute']
for n,c in list(m['cells'].items()):
 if c['type']=='$scopeinfo':assert not c['connections'] and not c['port_directions'];del m['cells'][n]
assert all(c['type']=='$lut' for c in m['cells'].values());assert len(m['ports']['x']['bits'])==len(early) and len(m['ports']['y']['bits'])==2;bits=dict(zip(m['ports']['x']['bits'],early));bits.update({'0':('constant',0),'1':('constant',1)});fresh=max(logical(c)[1]['O'] for c in prior['prospective_added'].values())+1;added={};pending=dict(m['cells'])
while pending:
 ready=[n for n,c in pending.items() if all(b in bits for b in c['connections']['A'])];assert ready
 for n in ready:
  c=pending.pop(n);mapped=[bits[b] for b in c['connections']['A']];variables=list(dict.fromkeys(b for b in mapped if isinstance(b,int)));table=int(c['parameters']['LUT'],2);mask=0
  for word in range(1<<len(variables)):
   vals={b:(word>>i)&1 for i,b in enumerate(variables)};index=sum((b[1] if isinstance(b,tuple) else vals[b])<<i for i,b in enumerate(mapped));mask|=((table>>index)&1)<<word
  if not variables:variables=[early[0]];mask=3 if mask else 0
  name=f'$tiny3tpu$write_address_carry_abc_{len(added)}';added[name]=packed(variables,fresh,mask);ob=c['connections']['Y'];assert len(ob)==1 and ob[0] not in bits;bits[ob[0]]=fresh;fresh+=1
mappedco=[bits[b] for b in m['ports']['y']['bits']];assert all(isinstance(b,int) for b in mappedco);final=packed([*mappedco,late],prior['output'],202);available=set(early)
for c in added.values():
 w,p,t=logical(c);assert {p['I'+str(i)] for i in range(w)}<=available;available.add(p['O'])
constants={b:int(c['type']=='PSEUDO_VCC') for c in prior['constant_drivers'].values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};leaves=prior['cuts'];external=[b for b in leaves if b not in constants];pos={b:i for i,b in enumerate(external)};bus='{'+','.join("1'b"+str(constants[b]) if b in constants else f'x[{pos[b]}]' for b in reversed(leaves))+'}'
def miter(final):return emit(prior['old_cone'],leaves,[prior['output']],'gold')+'\n'+emit({**added,root:final},leaves,[prior['output']],'gate')+f'\nmodule proof(input [{len(external)-1}:0] x,output same);wire a,b;gold g({bus},a);gate t({bus},b);assign same=a==b;endmodule\n'
mv=out/'miter.v';mv.write_text(miter(final));py=out/'prove.ys';py.write_text(f'read_verilog {lib} {mv}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -prove same 1 -verify\n');pl=out/'prove.log'
with pl.open('w') as f:subprocess.run([str(tool),'-s',str(py)],stdout=f,stderr=subprocess.STDOUT,check=True)
assert 'SAT proof finished - no model found: SUCCESS!' in pl.read_text();nv=out/'wrong-final.v';nv.write_text(miter(packed([*mappedco,late],prior['output'],53)));ny=out/'wrong-final.ys';ny.write_text(py.read_text().replace(str(mv),str(nv)));nl=out/'wrong-final.log'
with nl.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ny)],stdout=f,stderr=subprocess.STDOUT).returncode
assert rc!=0 and 'proof did fail' in nl.read_text();paths=[a.feasibility,Path(__file__),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),v,ys,log,out/'early.json',mv,py,pl,nv,ny,nl,tool,abc,lib];result={k:v for k,v in prior.items() if k not in ['sha256','added_origin','prospective_added','prospective_final']};result.update(original_feasibility=str(a.feasibility.resolve()),original_added_luts=len(prior['prospective_added']),prospective_added=added,prospective_final=final,prospective_added_luts=len(added),sha256={**prior['sha256'],**{str(q.resolve()):digest(q) for q in paths}});(out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(passed=True,original_added_luts=len(prior['prospective_added']),mapped_luts=len(added),independent_cut_inputs=len(external),actual_primitive_sat=True,late_carry_absent_from_early_cofactors=True,new_route_run=False)))
