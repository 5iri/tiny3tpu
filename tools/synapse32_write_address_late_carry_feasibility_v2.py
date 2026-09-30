"""Prove early cofactors of the write-address comparison around its late offset carry."""
import argparse,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();rp=a.route.resolve()/'manifest.json';r=json.loads(rp.read_text());assert r['passed'];source=a.route.resolve()/'input.json';assert r['sha256'][str(source)]==digest(source);m=json.loads(source.read_text())['modules']['top'];cs=m['cells'];ns=m['netnames'];late=ns['memory.main_write_offset_low[13]']['bits'];output=ns['memory.main_write_addr_changed_parallel']['bits'];assert len(late)==len(output)==1;late=late[0];output=output[0];drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};root=drv[output];memo={};active=set();constants={}
for n in ['$PACKER_GND_DRV','$PACKER_VCC_DRV']:
 c=cs[n];assert c['type'] in ['PSEUDO_GND','PSEUDO_VCC'];outs=[b for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs];assert len(outs)==1;constants[outs[0]]=int(c['type']=='PSEUDO_VCC')
physical_constants=dict(constants);constant_memo={};constant_active=set()
def constvalue(b):
 if b in constants:return constants[b]
 if b in constant_memo:return constant_memo[b]
 c=cs[drv[b]]
 if c['type'] not in ['SLICE_LUTX','SELMUX2_1']:constant_memo[b]=None;return None
 assert b not in constant_active;constant_active.add(b);w,p,t=logical(c);inputs=[p['I'+str(i)] for i in range(w)];known={i:constvalue(i) for i in inputs};free=sorted(i for i in known if known[i] is None);outputs=set()
 for word in range(1<<len(free)):
  vals={**known,**{b:(word>>i)&1 for i,b in enumerate(free)}};index=sum(vals[b]<<i for i,b in enumerate(inputs));outputs.add((t>>index)&1)
 constant_active.remove(b);v=next(iter(outputs)) if len(outputs)==1 else None;constant_memo[b]=v
 if v is not None:constants[b]=v
 return v
def dep(b):
 if b==late:return True
 if constvalue(b) is not None:return False
 if b in memo:return memo[b]
 n=drv[b];c=cs[n]
 if c['type']=='SLICE_FFX':memo[b]=False;return False
 assert c['type'] in ['SLICE_LUTX','SELMUX2_1','CARRY4'],(n,c['type'])
 assert b not in active;active.add(b)
 v=any(dep(v) for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for v in bs);active.remove(b);memo[b]=v;return v
cone={};cuts=set()
def walk(b):
 if b==late or not dep(b):cuts.add(b);return
 n=drv[b]
 if n in cone:return
 c=cs[n];assert c['type'] in ['SLICE_LUTX','SELMUX2_1'];w,p,t=logical(c)
 for i in range(w):walk(p['I'+str(i)])
 cone[n]=c
walk(output);assert root in cone and late in cuts;early=sorted(cuts-{late}-set(constants));assert early and all(not dep(b) for b in early)
constant_cone={}
def collect_constant(b):
 if b in physical_constants:return
 assert constvalue(b) is not None;n=drv[b]
 if n in constant_cone:return
 c=cs[n];w,p,t=logical(c)
 for i in range(w):
  child=p['I'+str(i)]
  if constvalue(child) is not None:collect_constant(child)
 constant_cone[n]=c
for b in cuts:
 if constvalue(b) is not None:collect_constant(b)
assert not set(constant_cone)&set(cone);old_combined={**constant_cone,**cone}

bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for n in ns.values() for b in n['bits']};fresh=max(b for b in bits if isinstance(b,int))+1;added={};origin={};cache={};co=[]
for choice in [0,1]:
 values={b:('s',b) for b in early};values[late]=('c',choice);values.update({b:('c',v) for b,v in constants.items()})
 for n,c in cone.items():
  w,p,t=logical(c);ins=[values[p['I'+str(i)]] for i in range(w)];leaves=sorted(set(v for k,v in ins if k=='s'));truth=[]
  for word in range(1<<len(leaves)):
   val={b:(word>>i)&1 for i,b in enumerate(leaves)};index=sum((v if k=='c' else val[v])<<i for i,(k,v) in enumerate(ins));truth.append((t>>index)&1)
  support=[i for i in range(len(leaves)) if any(truth[x]!=truth[x^(1<<i)] for x in range(len(truth)))];inputs=[leaves[i] for i in support];table=[truth[sum(((word>>i)&1)<<j for i,j in enumerate(support))] for word in range(1<<len(support))];mask=sum(v<<i for i,v in enumerate(table))
  if not inputs:v=('c',table[0])
  elif len(inputs)==1 and mask==2:v=('s',inputs[0])
  else:
   key=(tuple(inputs),mask)
   if key not in cache:
    nn=f'$tiny3tpu$write_address_carry_cofactor_{len(added)}';added[nn]=packed(inputs,fresh,mask);origin[nn]=n;cache[key]=fresh;fresh+=1
   v=('s',cache[key])
  values[p['O']]=v
 co.append(values[output])
physical_co=[v if k=='s' else next(b for b,c in constants.items() if c==v) for k,v in co];final=packed([*physical_co,late],output,202);candidate={**added,root:final};available=set(early)|set(constants)
for n,c in added.items():
 w,p,t=logical(c);assert {p['I'+str(i)] for i in range(w)}<=available;available.add(p['O'])
proof_cells={**old_combined,**candidate};proof_outputs={logical(c)[1]['O'] for c in proof_cells.values()};leaves=sorted({b for c in proof_cells.values() for p,b in logical(c)[1].items() if p!='O'}-proof_outputs);external=[b for b in leaves if b not in physical_constants];w=len(external);positions={b:i for i,b in enumerate(external)};bus='{'+','.join("1'b"+str(physical_constants[b]) if b in physical_constants else f'x[{positions[b]}]' for b in reversed(leaves))+'}';text=emit(old_combined,leaves,[output],'gold')+'\n'+emit(candidate,leaves,[output],'gate')+f'\nmodule proof(input [{w-1}:0] x,output same);wire a,b;gold g({bus},a);gate t({bus},b);assign same=a==b;endmodule\n'
out.mkdir();v=out/'miter.v';v.write_text(text);tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -prove same 1 -verify\n');log=out/'prove.log'
with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
negative=packed([*physical_co,late],output,53);nt=emit(old_combined,leaves,[output],'gold')+'\n'+emit({**added,root:negative},leaves,[output],'gate')+f'\nmodule proof(input [{w-1}:0] x,output same);wire a,b;gold g({bus},a);gate t({bus},b);assign same=a==b;endmodule\n';nv=out/'wrong-final.v';nv.write_text(nt);ny=out/'wrong-final.ys';ny.write_text(ys.read_text().replace(str(v),str(nv)));nl=out/'wrong-final.log'
with nl.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ny)],stdout=f,stderr=subprocess.STDOUT).returncode
assert rc!=0 and 'proof did fail' in nl.read_text();paths=[rp,source,Path(__file__),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),v,ys,log,nv,ny,nl,tool,lib]
(out/'manifest.json').write_text(json.dumps(dict(passed=True,root=root,output=output,late_carry=late,early_cuts=early,cuts=leaves,constant_drivers={n:cs[n] for n in ['$PACKER_GND_DRV','$PACKER_VCC_DRV']},old_cone=old_combined,derived_constant_cells=constant_cone,prospective_added=added,prospective_final=final,added_origin=origin,old_dependent_cells=len(cone),prospective_added_luts=len(added),independent_cut_inputs=w,actual_primitive_sat=True,wrong_final_lut_rejected=True,late_carry_absent_from_early_cofactors=True,soc_modified=False,new_route_run=False,scope='Read-only prospective Shannon expansion of the write-address comparison on the actual low-adder carry. Dependency discovery crosses combinational LUT/mux/carry inputs and terminates at registers/constants; every early cut is proved structurally independent of this carry. Primitive SAT binds the exact old and proposed packed functions. Original non-root cells remain; placement, macro constraints, observer cleanup, full route and all timing checks are pending.',sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print(json.dumps(dict(passed=True,old_dependent_cells=len(cone),derived_constant_cells=len(constant_cone),added_luts=len(added),independent_inputs=w,late_carry=late,actual_primitive_sat=True,new_route_run=False)))
