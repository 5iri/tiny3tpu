"""Prove prospective common-predicate factorizations; no packed SoC mutation or route."""
import argparse,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
p=argparse.ArgumentParser();p.add_argument('--candidates',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();data=json.loads(a.candidates.read_text())
for n,h in data['sha256'].items():assert digest(n)==h,n
assert len(data['sha256'])==1;source=Path(next(iter(data['sha256'])));m=json.loads(source.read_text())['modules']['top'];cs=m['cells'];g=cs['$PACKER_GND_DRV'];assert g['type']=='PSEUDO_GND' and [b for p,bs in g['connections'].items() if g['port_directions'][p]=='output' for b in bs]==[241167];bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for n in m['netnames'].values() for b in n['bits']}|{b for p in m['ports'].values() for b in p['bits']};fresh=max(b for b in bits if isinstance(b,int))+1
out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';rows=[];paths=[a.candidates,source,Path(__file__),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),tool,lib]
for i,r in enumerate(v for v in data['candidates'] if not v.get('already_encoded')):
 root=r['root'];old={n:cs[n] for n in [root,*r['children']]};assert cs[root]['attributes']['CONSTR_CHILDREN'].split(';')==r['children'];assert r['late']==[105590,105551,105571] and r['common_lut3_table']==253
 common=packed(r['late'],fresh,253);new=packed([*r['early'],fresh],r['output'],r['root_lut6_table']);cuts=[*r['early'],*r['late']];assert len(set(cuts))==8;ov=emit(old,[*cuts,241167],[r['output']],'gold')
 def make(mask,ground):
  final=packed([*r['early'],fresh],r['output'],mask);nv=emit({'common':common,'root':final},cuts,[r['output']],'candidate');return ov+'\n'+nv+f"\nmodule proof(input [7:0] x,output same);wire a,b;gold g({{1'b{ground},x}},a);candidate c(x,b);assign same=a==b;endmodule\n"
 checks=[]
 for label,mask,ground,positive in [('correct',r['root_lut6_table'],0,True),('wrong_lut',r['root_lut6_table']^1,0,False),('wrong_ground',r['root_lut6_table'],1,False)]:
  v=out/f'miter-{i}-{label}.v';v.write_text(make(mask,ground));ys=out/f'prove-{i}-{label}.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/f'prove-{i}-{label}.log'
  with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
  if positive:assert rc==0 and 'SUCCESS!' in log.read_text()
  else:assert rc!=0 and 'proof did fail' in log.read_text()
  checks.append(dict(label=label,expected_outcome_verified=True,miter=str(v),log=str(log)));paths.extend([v,ys,log])
 rows.append(dict(root=root,group=r['group'],checks=checks))
assert len(rows)==14;(out/'manifest.json').write_text(json.dumps(dict(passed=True,actual_primitive_sat_targets=14,negative_sat_checks=28,targets=rows,soc_modified=False,new_route_run=False,scope='Prospective common LUT3 plus per-output LUT6 equivalence for all 14 unencoded capture macros, with actual original primitives and actual ground-driver provenance. Complete packed implementation, legal placement and routing remain pending.',sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print('PASS 14 prospective primitive proofs and 28 negative SAT checks; SoC and routing unchanged')
