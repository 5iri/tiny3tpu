"""Inline the signed branch carry's generate predicate into its existing local LUT."""
import gc
gc.disable()
import argparse,copy,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_cpu_branch_decode_move import apply_verified as apply_base
from synapse32_packed_timer_mid_zero_flag import FIELDS
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
TARGET='$flatten\\soc.\\cpu.$1282.G[0]$LUT$8160'
def spec(m):
 cs=m['cells'];w,p,t=logical(cs[TARGET]);assert w==1 and t==2
 drivers=[n for n,c in cs.items() if any(p['I0'] in bs for k,bs in c['connections'].items() if c['port_directions'][k]=='output')];assert len(drivers)==1;driver=drivers[0];w,q,t=logical(cs[driver]);assert w==4 and t==244
 inputs=[q['I'+str(i)] for i in range(w)];new=packed(inputs,p['O'],t);new['hide_name']=cs[TARGET]['hide_name'];new['attributes'].update({k:v for k,v in cs[TARGET]['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k!='X_ORIG_TYPE'})
 assert new['attributes']['CONSTR_PARENT']=='$flatten\\soc.\\cpu.$1282.genblk1.slice[0].genblk1.carry4'
 sibling='$flatten\\soc.\\cpu.$1282.genblk1.S[0]$LUT$8158';sw,sp,st=logical(cs[sibling]);assert sw==1 and st==2 and len(set(inputs+[sp['I0']]))==5
 return dict(old={driver:cs[driver],TARGET:cs[TARGET]},replacement=new,inputs=inputs,output=p['O'],sibling=cs[sibling])
def miter(s):
 return emit(s['old'],s['inputs'],[s['output']],'gold')+'\n'+emit({TARGET:s['replacement']},s['inputs'],[s['output']],'gate')+"\nmodule proof(input [3:0] x,output same);wire a,b;gold g(x,a);gate t(x,b);assign same=a==b;endmodule\n"
def validate(p,prior,base,gold):
 s=spec(base['modules']['top']);assert p['original_cells']=={**prior['original_cells'],**{n:gold['modules']['top']['cells'][n] for n in s['old']}};assert TARGET not in prior['replacements'];assert p['replacements']=={**prior['replacements'],TARGET:s['replacement']}
 for k in FIELDS:
  if k not in ['original_cells','replacements']:assert p[k]==prior[k]
 proof=p['inline_proof'];assert Path(proof['miter']).read_text()==miter(s)
 for n,h in proof['sha256'].items():assert digest(n)==h,n
 assert 'SAT proof finished - no model found: SUCCESS!' in Path(proof['log']).read_text();base['modules']['top']['cells'][TARGET]=copy.deepcopy(s['replacement']);return base

def apply_verified(p,design):
 bp=Path(p['inline_base']);assert p['passed'] and digest(bp)==p['inline_base_sha256'];prior=json.loads(bp.read_text());return validate(p,prior,apply_base(prior,design),design)
def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch'])==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_branch_carry_input_inline',inline_base=str(bp),inline_base_sha256=digest(bp));patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in s['old']});patch['replacements'][TARGET]=s['replacement'];out.mkdir();v=out/'miter.v';v.write_text(miter(s));tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -prove same 1 -verify\n');log=out/'prove.log'
 with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 paths=[v,ys,log,tool,lib];negative=copy.deepcopy(s);negative['replacement']['parameters']['INIT']='0'*16;nv=out/'negative.v';nv.write_text(miter(negative));ny=out/'negative.ys';ny.write_text(ys.read_text().replace(str(v),str(nv)));nl=out/'negative.log'
 with nl.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ny)],stdout=f,stderr=subprocess.STDOUT).returncode
 assert rc!=0 and 'proof did fail' in nl.read_text();paths += [nv,ny,nl]
 patch['inline_proof']=dict(miter=str(v),log=str(log),wrong_predicate_rejected=True,sha256={str(q.resolve()):digest(q) for q in paths});validate(patch,prior,base,gold);patch['sha256']=dict(prior['sha256']);patch['sha256'].update(patch['inline_proof']['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,source,Path(__file__),Path(__file__).with_name('synapse32_packed_cpu_branch_decode_move.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,changed_luts=1,added_state=0,added_latency_cycles=0,shared_lut_input_union=5,actual_primitive_sat=True,wrong_predicate_rejected=True)))
if __name__=='__main__':main()
