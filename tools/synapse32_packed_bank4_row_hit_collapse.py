"""Exact two-level bank4 row equality, without changing any sequential state."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_mid_zero_flag import apply_verified as apply_base,FIELDS
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
PREFIX='$tiny3tpu$bank4_row_eq_'
FEAS=Path('build-grade2-bank4-row-hit-feasibility/manifest.json').resolve()
CONE=Path('build-grade2-timer-mid-zero-flag-route/bank4-row-cone-feasibility.json').resolve()
def spec(m):
 f=json.loads(FEAS.read_text());r=json.loads(CONE.read_text());cs=m['cells'];assert f['passed']
 for p,h in f['sha256'].items():assert digest(p)==h,p
 def functional(c):
  c=copy.deepcopy(c);c['attributes']={k:v for k,v in c['attributes'].items() if k not in ['NEXTPNR_BEL','BEL_STRENGTH']};return c
 assert all(functional(cs[n])==functional(c) for n,c in {**r['combinational_cells'],**r['leaf_cells']}.items())
 bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for p in m['ports'].values() for b in p['bits']};fresh=max(b for b in bits if isinstance(b,int))+1
 added={};nets={};eq=[]
 for j,start in enumerate(range(0,14,3)):
  inputs=[b for i in range(start,min(14,start+3)) for b in [f['pipe_q'][i],f['row_q'][i]]];w=len(inputs);mask=sum(int(all(((v>>i)&1)==((v>>(i+1))&1) for i in range(0,w,2)))<<v for v in range(1<<w));n=PREFIX+str(j);added[n]=packed(inputs,fresh,mask);nets[n+'$net']=dict(hide_name=0,bits=[fresh],attributes={});eq.append(fresh);fresh+=1
 root=f['source_root'];replacement=packed(eq+[f['open_q']],f['predicate_output'],1<<63);replacement['hide_name']=cs[root]['hide_name'];replacement['attributes'].update({k:v for k,v in cs[root]['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});replacements={root:replacement};children=cs[root]['attributes']['CONSTR_CHILDREN'].split(';');assert len(children)==6
 for n in children:
  assert cs[n]['attributes']['CONSTR_PARENT']==root;c=copy.deepcopy(cs[n]);c['attributes']={k:v for k,v in c['attributes'].items() if not k.startswith('CONSTR_')};replacements[n]=c
 return dict(f=f,old=r['combinational_cells'],source=r['leaf_cells'],added=added,nets=nets,replacements=replacements,children=children)
def miter(s):
 f=s['f'];leaves=f['pipe_q']+f['row_q']+[f['open_q'],241167];root=f['source_root'];new={**s['added'],root:s['replacements'][root]};text=emit(s['old'],leaves,[f['predicate_output']],'gold')+'\n'+emit(new,leaves,[f['predicate_output']],'gate')+'\n';return text+"module proof(input [28:0] x,output same);wire a,b;gold g({1'b0,x},a);gate t({1'b0,x},b);assign same=a==b;endmodule\n"
def validate(p,prior,base,gold):
 s=spec(base['modules']['top']);assert p['original_cells']=={**prior['original_cells'],**{n:gold['modules']['top']['cells'][n] for n in {*s['old'],*s['source']}}}
 for k,new in [('replacements',s['replacements']),('added_cells',s['added']),('added_netnames',s['nets'])]:assert not set(prior[k])&set(new);assert p[k]=={**prior[k],**new}
 for k in ['checkpoint','removed_cells','removed_netnames','added_latency_cycles']:assert p[k]==prior[k]
 assert p['added_latency_cycles']==0 and p['added_state_cells']==0
 assert set(p['placements'])==set(prior['placements'])|set(s['added'])|{s['f']['source_root']};assert all(p['placements'][n]==v for n,v in prior['placements'].items())
 proof=p['row_proof'];assert Path(proof['miter']).read_text()==miter(s)
 for n,h in proof['sha256'].items():assert digest(n)==h,n
 assert 'SAT proof finished - no model found: SUCCESS!' in Path(proof['log']).read_text()
 m=base['modules']['top'];m['cells'].update(copy.deepcopy(s['replacements']));m['cells'].update(copy.deepcopy(s['added']));m['netnames'].update(copy.deepcopy(s['nets']));return base

def apply_verified(p,design):
 bp=Path(p['row_base_path']);assert p['passed'] and digest(bp)==p['row_base_sha256'];prior=json.loads(bp.read_text());return validate(p,prior,apply_base(prior,design),design)
def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch'])==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_bank4_row_hit_two_level_equality',row_base_path=str(bp),row_base_sha256=digest(bp),added_state_cells=0)
 patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in {*s['old'],*s['source']}})
 for k,new in [('replacements',s['replacements']),('added_cells',s['added']),('added_netnames',s['nets'])]:patch[k].update(new)
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL'))}
 def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
 def allocate(name,target):
  choices=[site+'/'+l+'6LUT' for site in sites-bad for l in 'ABCD' if all(site+'/'+l+t not in occupied for t in ['5LUT','6LUT'])];assert choices
  b=min(choices,key=lambda b:(sum(abs(v-w) for v,w in zip(xy(b),target)),b));patch['placements'][name]=b;occupied.add(b);return xy(b)
 allocate(s['f']['source_root'],(116,22))
 for j,start in enumerate(range(0,14,3)):
  locs=[xy(placed[n]['attributes']['NEXTPNR_BEL']) for i in range(start,min(14,start+3)) for n in [s['f']['pipe_registers'][i],s['f']['row_registers'][i]]];allocate(PREFIX+str(j),tuple(sum(v[k] for v in locs)//len(locs) for k in range(2)))
 out.mkdir();v=out/'miter.v';v.write_text(miter(s));tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -prove same 1 -verify\n');log=out/'prove.log'
 with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 patch['row_proof']=dict(miter=str(v),log=str(log),sha256={str(q.resolve()):digest(q) for q in [v,ys,log,tool,lib,FEAS,CONE]});validate(patch,prior,base,gold);patch['sha256']=dict(prior['sha256']);patch['sha256'].update(patch['row_proof']['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_mid_zero_flag.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,added_state_cells=0,added_luts=5,added_latency_cycles=0,actual_primitive_sat=True,placements={n:patch['placements'][n] for n in [s['f']['source_root'],*s['added']]})))
if __name__=='__main__':main()
