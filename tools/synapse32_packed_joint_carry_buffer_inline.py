"""Apply the jointly proved carry-local LUT inlining set without altering any state."""
import gc
gc.disable()
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_branch_carry_input_inline import apply_verified as apply_base
from synapse32_packed_timer_mid_zero_flag import FIELDS
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
FEAS=Path('build-grade2-joint-carry-inline-feasibility/manifest.json').resolve()
def spec(m):
 f=json.loads(FEAS.read_text());assert f['passed'] and f['actual_primitive_sat'] and f['selected_count']==394;cs=m['cells'];new={};sources={}
 for n,h in f['sha256'].items():assert digest(n)==h,n
 for item in f['selection_order']:
  n=item['target'];d=item['driver'];c=cs[n];u=cs[d];assert c['type']=='SLICE_LUTX' and u['type']=='SLICE_LUTX';w,p,t=logical(c);uw,up,ut=logical(u);assert w==1 and t==2 and p['I0']==up['O'] and uw<=5
  parent=c['attributes']['CONSTR_PARENT'];assert parent==item['carry'] and cs[parent]['type']=='CARRY4';inputs=[up['I'+str(i)] for i in range(uw)];replacement=packed(inputs,p['O'],ut);replacement['hide_name']=c['hide_name'];replacement['attributes'].update({k:v for k,v in c['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k!='X_ORIG_TYPE'});new[n]=replacement;sources[n]=c;sources[d]=u
  other=item['paired_cell']
  if other:sources[other]=cs[other]
 assert len(new)==394
 for item in f['selection_order']:
  n=item['target'];other=new.get(item['paired_cell'],cs.get(item['paired_cell']));w,p,t=logical(new[n]);bits={p['I'+str(i)] for i in range(w)}
  if other:ow,op,ot=logical(other);bits|={op['I'+str(i)] for i in range(ow)}
  assert len(bits)<=5
  def functional(c):
   c=copy.deepcopy(c);c['attributes']={k:v for k,v in c['attributes'].items() if k not in ['BEL_STRENGTH','NEXTPNR_BEL']};return c
  assert functional(new[n])==functional(f['prospective_replacements'][n])
 modules=[];ports=[];offset=0
 for i,item in enumerate(f['selection_order']):
  n=item['target'];d=item['driver'];_,bp,_=logical(cs[n]);w,p,t=logical(cs[d]);leaves=sorted(set(p['I'+str(j)] for j in range(w)));width=len(leaves);modules += [emit({d:cs[d],n:cs[n]},leaves,[bp['O']],f'gold{i}'),emit({n:new[n]},leaves,[bp['O']],f'gate{i}')];ports += [(offset,width)];offset+=width
 lines=[f'module proof(input [{offset-1}:0] x,output same);',f'wire [{len(new)-1}:0] g,t;']
 for i,(start,width) in enumerate(ports):lines += [f'gold{i} a{i}(x[{start+width-1}:{start}],g[{i}]);',f'gate{i} b{i}(x[{start+width-1}:{start}],t[{i}]);']
 lines += ['assign same=g==t;','endmodule'];assert (FEAS.parent/'miter.v').read_text()=='\n'.join(modules+lines)+'\n';assert 'SAT proof finished - no model found: SUCCESS!' in (FEAS.parent/'prove.log').read_text();return new,sources

def validate(p,prior,base,gold):
 new,sources=spec(base['modules']['top']);assert not set(new)&set(prior['added_cells']);assert p['joint_source_cells']==sources;original=gold['modules']['top']['cells'];assert p['original_cells']=={**prior['original_cells'],**{n:original[n] for n in sources if n in original}};assert p['replacements']=={**prior['replacements'],**new}
 for k in FIELDS:
  if k not in ['original_cells','replacements']:assert p[k]==prior[k]
 assert p['added_latency_cycles']==0 and p['changed_carry_local_luts']==394;assert p['joint_feasibility']==str(FEAS) and p['joint_feasibility_sha256']==digest(FEAS);base['modules']['top']['cells'].update(copy.deepcopy(new));return base

def apply_verified(p,design):
 bp=Path(p['joint_base']);assert p['passed'] and digest(bp)==p['joint_base_sha256'];prior=json.loads(bp.read_text());return validate(p,prior,apply_base(prior,design),design)
def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';r=json.loads(rp.read_text());assert r['passed'] and Path(r['patch'])==bp
 for d in [prior,r]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);new,sources=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_joint_carry_buffer_inline',joint_base=str(bp),joint_base_sha256=digest(bp),joint_source_cells=sources,joint_feasibility=str(FEAS),joint_feasibility_sha256=digest(FEAS),changed_carry_local_luts=len(new));original=gold['modules']['top']['cells'];patch['original_cells'].update({n:original[n] for n in sources if n in original});patch['replacements'].update(new);validate(patch,prior,base,gold);negative=FEAS.parent/'negative-controls/manifest.json';neg=json.loads(negative.read_text());assert neg['passed']
 for n,h in neg['sha256'].items():assert digest(n)==h,n
 out.mkdir();patch['sha256']=dict(prior['sha256']);patch['sha256'].update(json.loads(FEAS.read_text())['sha256']);patch['sha256'].update(neg['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,source,FEAS,negative,Path(__file__),Path(__file__).with_name('synapse32_packed_branch_carry_input_inline.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,changed_carry_local_luts=394,added_state=0,added_latency_cycles=0,actual_primitive_sat=True,joint_five_input_limit=True)))
if __name__=='__main__':main()
