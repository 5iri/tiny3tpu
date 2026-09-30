"""Same-edge bank4 row-hit observer, with actual packed-primitive induction."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_mid_zero_flag import apply_verified as apply_base,FIELDS
from synapse32_packed_counter_encoding import logical,emit
from synapse32_packed_selector_patch_v4 import packed
from synapse32_bank4_row_hit_observer_audit import audit
PREFIX='$tiny3tpu$bank4_row_hit_';FLAG=PREFIX+'flag'
FEAS=Path('build-grade2-bank4-row-hit-feasibility/manifest.json').resolve()
CONE=Path('build-grade2-timer-mid-zero-flag-route/bank4-row-cone-feasibility.json').resolve()
def spec(m):
 f=json.loads(FEAS.read_text());r=json.loads(CONE.read_text());cs=m['cells'];assert f['passed'] and f['actual_primitive_induction']
 for p,h in f['sha256'].items():assert digest(p)==h,p
 def functional(c):
  c=copy.deepcopy(c);c['attributes']={k:v for k,v in c['attributes'].items() if k not in ['NEXTPNR_BEL','BEL_STRENGTH']};return c
 assert all(functional(cs[n])==functional(c) for n,c in {**r['combinational_cells'],**r['leaf_cells']}.items())
 assert all(functional(cs[n])==functional(c) for n,c in f['source_registers'].items())
 audit(m)
 bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for p in m['ports'].values() for b in p['bits']};fresh=max(b for b in bits if isinstance(b,int))+1
 added={};nets={}
 def lut(name,inputs,mask):
  nonlocal fresh
  n=PREFIX+name;added[n]=packed(inputs,fresh,mask);nets[n+'$net']=dict(hide_name=0,bits=[fresh],attributes={});fresh+=1;return fresh-1
 eq=[lut('eq'+str(i),[f['pipe_d'][i],f['pipe_q'][i],f['row_d'][i],f['row_q'][i],f['ce_pipe'],f['ce_row']],f['eq_lut6_table']) for i in range(14)]
 a=[lut('and0',eq[:6],1<<63),lut('and1',eq[6:12],1<<63),lut('and2',eq[12:],8)]
 op=lut('open_next',[f['open_q'],f['ce_row']],14);fd=lut('next',a+[f['common_source_reset'],op],0xff800000)
 ff=copy.deepcopy(cs[f['open_register']]);ff['attributes']={k:v for k,v in ff['attributes'].items() if not k.startswith('CONSTR_') and k not in ['NEXTPNR_BEL','BEL_STRENGTH']};ff['connections']=dict(CK=[f['flag_clock']],SR=[f['flag_reset']],D=[fd],CE=[],Q=[f['predicate_output']]);added[FLAG]=ff
 root=f['source_root'];old=copy.deepcopy(cs[root]);port=next(p for p,d in old['port_directions'].items() if d=='output');assert old['connections'][port]==[f['predicate_output']];old['connections'][port]=[fresh];nets[PREFIX+'old_predicate_unused']=dict(hide_name=0,bits=[fresh],attributes={})
 return dict(f=f,old=r['combinational_cells'],source=r['leaf_cells'],added=added,nets=nets,replacements={root:old})
def miter(s):
 f=s['f'];new={n:c for n,c in s['added'].items() if n!=FLAG};q=f['pipe_q']+f['row_q']+[f['open_q']];oldin=q+[241167]
 leaves=sorted({b for c in new.values() for p,b in logical(c)[1].items() if p!='O'}-{logical(c)[1]['O'] for c in new.values()})
 text=emit(s['old'],oldin,[f['predicate_output']],'old_predicate')+'\n'+emit(new,leaves,s['added'][FLAG]['connections']['D'],'next_predicate')+'\n'
 regs=f['source_registers'];external=sorted(({b for c in regs.values() for p,bs in c['connections'].items() if p not in ['CK','Q'] for b in bs}|set(leaves)) -set(q)-{241167,241169})
 bits=sorted(set(q+leaves+external+[241167,241169]));lines=[f'module proof(input clk,input [{len(external)-1}:0] x,output same);','wire '+','.join('n'+str(b) for b in bits)+';','wire expected,fd,flag;',"assign n241167=1'b0;assign n241169=1'b1;"]
 lines += [f'assign n{b}=x[{i}];' for i,b in enumerate(external)]
 for i,c in enumerate(regs.values()):
  p=c['connections'];assert c['parameters']=={'INIT':'0'} and c['attributes']['X_ORIG_TYPE']=='FDRE'
  lines.append(f"FDRE #(.INIT(1'b0)) r{i}(.C(clk),.R(n{p['SR'][0]}),.CE(n{p['CE'][0]}),.D(n{p['D'][0]}),.Q(n{p['Q'][0]}));")
 def bus(bs):return '{'+','.join('n'+str(b) for b in reversed(bs))+'}'
 ff=s['added'][FLAG];assert ff['parameters']=={'INIT':'0'} and ff['connections']==dict(CK=[156059],SR=[138431],CE=[],D=ff['connections']['D'],Q=[94901])
 lines += [f'old_predicate g({bus(oldin)},expected);',f'next_predicate ng({bus(leaves)},fd);',"FDRE #(.INIT(1'b0)) f(.C(clk),.R(n138431),.CE(1'b1),.D(fd),.Q(flag));",'assign same=flag==expected;','endmodule']
 return text+'\n'.join(lines)+'\n'
def validate(p,prior,base,gold):
 s=spec(base['modules']['top']);assert p['row_source_cells']==s['source'];assert p['original_cells']=={**prior['original_cells'],**{n:gold['modules']['top']['cells'][n] for n in {*s['old'],*s['source']}}}
 for k,new in [('replacements',s['replacements']),('added_cells',s['added']),('added_netnames',s['nets'])]:assert not set(prior[k])&set(new);assert p[k]=={**prior[k],**new}
 for k in ['checkpoint','removed_cells','removed_netnames','added_latency_cycles']:assert p[k]==prior[k]
 assert p['added_latency_cycles']==0 and p['redundant_row_hit_ff_added']==1
 assert set(p['placements'])==set(prior['placements'])|set(s['added']);assert all(p['placements'][n]==v for n,v in prior['placements'].items())
 assert p['placements'][FLAG]==p['placements'][PREFIX+'next'][:-4]+'FF'
 proof=p['row_proof'];assert Path(proof['miter']).read_text()==miter(s)
 for n,h in proof['sha256'].items():assert digest(n)==h,n
 assert 'Induction step proven: SUCCESS!' in Path(proof['log']).read_text()
 contract=Path(proof['packer_contract']).read_text();assert 'ce->name == vcc' in contract and 'disconnect_port(ctx, ci, id_CE);' in contract
 m=base['modules']['top'];m['cells'].update(copy.deepcopy(s['replacements']));m['cells'].update(copy.deepcopy(s['added']));m['netnames'].update(copy.deepcopy(s['nets']));audit(m);return base

def apply_verified(p,design):
 bp=Path(p['row_base_path']);assert p['passed'] and digest(bp)==p['row_base_sha256'];prior=json.loads(bp.read_text());return validate(p,prior,apply_base(prior,design),design)
def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch'])==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_same_edge_bank4_row_hit_flag',row_base_path=str(bp),row_base_sha256=digest(bp),row_source_cells=s['source'],redundant_row_hit_ff_added=1)
 patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in {*s['old'],*s['source']}})
 for k,new in [('replacements',s['replacements']),('added_cells',s['added']),('added_netnames',s['nets'])]:patch[k].update(new)
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL'))}
 def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
 # Keep the final predicate and its register together in a slice without another control set.
 ff_sites={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type']=='SLICE_FFX'}
 def free_lut(site,l):return all(site+'/'+l+t not in occupied for t in ['5LUT','6LUT'])
 def allocate(name,target,flag=False):
  choices=[site+'/'+l+'6LUT' for site in sites-bad-(ff_sites if flag else set()) for l in 'ABCD' if free_lut(site,l) and (not flag or all(site+'/'+l+t not in occupied for t in ['FF','5FF']))];assert choices
  b=min(choices,key=lambda b:(sum(abs(v-w) for v,w in zip(xy(b),target)),b));patch['placements'][name]=b;occupied.add(b)
  if flag:patch['placements'][FLAG]=b[:-4]+'FF';occupied.add(b[:-4]+'FF')
  return xy(b)
 center=allocate(PREFIX+'next',(116,22),True)
 for n in ['and0','and1','and2','open_next']:allocate(PREFIX+n,center)
 for i in range(14):
  locs=[xy(placed[n]['attributes']['NEXTPNR_BEL']) for n in [s['f']['pipe_registers'][i],s['f']['row_registers'][i]]];allocate(PREFIX+'eq'+str(i),tuple(sum(v[j] for v in locs)//2 for j in range(2)))
 out.mkdir();v=out/'miter.v';v.write_text(miter(s));tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';contract=Path('build-grade2-refresher-flag-feasibility/packer-ce-contract.cc').resolve();ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -seq 4 -prove same 1 -verify\nsat -seq 3 -tempinduct -maxsteps 8 -prove same 1 -verify\n');log=out/'prove.log'
 with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 patch['row_proof']=dict(miter=str(v),log=str(log),packer_contract=str(contract),sha256={str(q.resolve()):digest(q) for q in [v,ys,log,tool,lib,contract,FEAS,CONE]});validate(patch,prior,base,gold);patch['sha256']=dict(prior['sha256']);patch['sha256'].update(patch['row_proof']['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_mid_zero_flag.py'),Path(__file__).with_name('synapse32_bank4_row_hit_observer_audit.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,added_redundant_ff=1,added_luts=19,added_latency_cycles=0,actual_primitive_induction=True,placements={n:patch['placements'][n] for n in s['added']})))
if __name__=='__main__':main()
