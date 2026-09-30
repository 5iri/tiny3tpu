"""Prove a jointly pin-compatible set of carry-buffer inlining candidates, without routing."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
p=argparse.ArgumentParser();p.add_argument('--inventory',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();inventory=json.loads(a.inventory.read_text());assert inventory['passed']
for n,h in inventory['sha256'].items():assert digest(n)==h,n
assert inventory['sha256'][str(a.source.resolve())]==digest(a.source);m=json.loads(a.source.read_text())['modules']['top'];cs=m['cells'];replacements={};selected=[];rejected=[]
def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
def rank(item):
 p=xy(item['bel']);q=xy(cs[item['driver']]['attributes']['NEXTPNR_BEL']);return (-sum(abs(a-b) for a,b in zip(p,q)),-item['source_width'],item['target'])
for item in sorted(inventory['candidates'],key=rank):
 n=item['target'];d=item['driver'];w,q,t=logical(cs[d]);_,bp,bt=logical(cs[n]);assert bt==2 and bp['I0']==q['O'];inputs=[q['I'+str(i)] for i in range(w)];other=replacements.get(item['paired_cell'],cs.get(item['paired_cell']))
 if other:ow,op,ot=logical(other);union=set(inputs+[op['I'+str(i)] for i in range(ow)])
 else:union=set(inputs)
 if len(union)>5:rejected.append(n);continue
 c=packed(inputs,bp['O'],t);c['hide_name']=cs[n]['hide_name'];c['attributes'].update({k:v for k,v in cs[n]['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k!='X_ORIG_TYPE'});replacements[n]=c;selected.append(item)
for item in selected:
 n=item['target'];other=replacements.get(item['paired_cell'],cs.get(item['paired_cell']));w,p,t=logical(replacements[n]);bits={p['I'+str(i)] for i in range(w)}
 if other:ow,op,ot=logical(other);bits|={op['I'+str(i)] for i in range(ow)}
 assert len(bits)<=5
modules=[];ports=[];offset=0
for i,item in enumerate(selected):
 n=item['target'];d=item['driver'];_,bp,_=logical(cs[n]);w,p,t=logical(cs[d]);leaves=sorted(set(p['I'+str(j)] for j in range(w)));width=len(leaves);modules += [emit({d:cs[d],n:cs[n]},leaves,[bp['O']],f'gold{i}'),emit({n:replacements[n]},leaves,[bp['O']],f'gate{i}')];ports += [(offset,width)];offset+=width
lines=[f'module proof(input [{offset-1}:0] x,output same);',f'wire [{len(selected)-1}:0] g,t;']
for i,(start,width) in enumerate(ports):lines += [f'gold{i} a{i}(x[{start+width-1}:{start}],g[{i}]);',f'gate{i} b{i}(x[{start+width-1}:{start}],t[{i}]);']
lines += ['assign same=g==t;','endmodule'];text='\n'.join(modules+lines)+'\n';out.mkdir();v=out/'miter.v';v.write_text(text);tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -prove same 1 -verify\n');log=out/'prove.log'
with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text();negative=text.replace('assign same=g==t;',"assign same=(g==t)^1'b1;");nv=out/'negative.v';nv.write_text(negative);ny=out/'negative.ys';ny.write_text(ys.read_text().replace(str(v),str(nv)));nl=out/'negative.log'
with nl.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ny)],stdout=f,stderr=subprocess.STDOUT).returncode
assert rc!=0 and 'proof did fail' in nl.read_text();paths=[a.inventory,a.source,Path(__file__),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),v,ys,log,nv,ny,nl,tool,lib]
(out/'manifest.json').write_text(json.dumps(dict(passed=True,selected_count=len(selected),rejected_joint_pin_conflicts=len(rejected),selection_order=selected,rejected_targets=rejected,prospective_replacements=replacements,independent_cut_inputs=offset,actual_primitive_sat=True,negative_false_equivalence_rejected=True,soc_modified=False,new_route_run=False,scope='Prospective local identity-buffer inlining, selected greedily by source-to-buffer Manhattan distance with a joint five-input limit for each A5/A6 LUT pair. All selected local old/new functions are proved together over independent cut inputs. Original upstream cells stay in place. No cycles/state change, packed SoC edit, route result or timing gain is claimed. Physical pin fixup and all timing checks remain mandatory.',sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print(json.dumps(dict(passed=True,selected=len(selected),joint_pin_conflicts=len(rejected),independent_cut_inputs=offset,soc_modified=False,new_route_run=False)))
