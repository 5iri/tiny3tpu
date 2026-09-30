"""Preserve the timer's exact eight-bit zero predicate with a same-edge flag."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_zero_flag import apply_verified as apply_base
from synapse32_packed_counter_encoding import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']
EARLY='$tiny3tpu$timer_mid_zero_next_early';FLAG='$tiny3tpu$timer_mid_zero_flag'

def spec(m):
 cs=m['cells'];root=next(n for n,c in cs.items() if '$217670.' in n and c['attributes'].get('X_ORIG_TYPE')=='MUXF8');children=cs[root]['attributes']['CONSTR_CHILDREN'].split(';');assert len(children)==6
 g=cs['$PACKER_GND_DRV'];assert g['type']=='PSEUDO_GND' and [b for p,bs in g['connections'].items() if g['port_directions'][p]=='output' for b in bs]==[241167]
 nodes={n:cs[n] for n in [root,*children]};outs={logical(c)[1]['O'] for c in nodes.values()};ins={b for c in nodes.values() for p,b in logical(c)[1].items() if p!='O'}-outs;assert 241167 in ins;cuts=sorted(ins-{241167});assert cuts==[54812,54814,54816,54818,54820,54822,54829,54838]
 order={};available=set(ins);pending=dict(nodes)
 while pending:
  ready=[n for n,c in pending.items() if {b for p,b in logical(c)[1].items() if p!='O'}<=available];assert ready
  for n in ready:c=pending.pop(n);order[n]=c;available.add(logical(c)[1]['O'])
 oldout=logical(cs[root])[1]['O'];assert oldout==54746
 for word in range(256):
  vs={b:(word>>i)&1 for i,b in enumerate(cuts)};vs[241167]=0
  for c in order.values():vs[logical(c)[1]['O']]=evaluate(c,vs)
  assert vs[oldout]==int(word==0)
 drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};regs=[drv[b] for b in cuts];ds=[];initial=[];resets=[]
 for i,n in enumerate(regs):
  c=cs[n];kind=c['attributes']['X_ORIG_TYPE'];assert c['type']=='SLICE_FFX' and kind in ['FDRE','FDSE'] and c['attributes']['X_FFSYNC'].strip()=='1';assert c['parameters'] in [{'INIT':'0'},{'INIT':'1'}]
  assert c['port_directions']==dict(CK='input',SR='input',D='input',CE='input',Q='output')
  assert all(c['attributes']['X_ORIG_PORT_'+p]==v for p,v in dict(CK='C',SR='R' if kind=='FDRE' else 'S',D='D',CE='CE',Q='Q').items())
  assert c['connections']['CK']==[156059] and c['connections']['SR']==[138579] and c['connections']['CE']==[] and c['connections']['Q']==[cuts[i]] and len(c['connections']['D'])==1
  ds+=c['connections']['D'];initial.append(int(c['parameters']['INIT']));resets.append(int(kind=='FDSE'))
 assert any(initial) and any(resets) and len(set(ds+cuts))==16
 bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for p in m['ports'].values() for b in p['bits']};fresh=max(b for b in bits if isinstance(b,int))+1
 early=packed(ds[:6],fresh,1);final=packed([fresh,*ds[6:]],fresh+1,2)
 final['hide_name']=cs[root]['hide_name'];final['attributes'].update({k:v for k,v in cs[root]['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']})
 ff=copy.deepcopy(cs[regs[6]]);assert ff['attributes']['X_ORIG_TYPE']=='FDRE' and ff['parameters']=={'INIT':'0'};ff['attributes']={k:v for k,v in ff['attributes'].items() if not k.startswith('CONSTR_') and k not in ['NEXTPNR_BEL','BEL_STRENGTH']};ff['connections']=dict(CK=[156059],SR=[138579],D=[fresh+1],CE=[],Q=[oldout])
 replacements={root:final}
 for n in children:
  assert cs[n]['attributes']['CONSTR_PARENT']==root;c=copy.deepcopy(cs[n]);c['attributes']={k:v for k,v in c['attributes'].items() if not k.startswith('CONSTR_')};replacements[n]=c
 return dict(root=root,children=children,cuts=cuts,old=order,oldout=oldout,regs=regs,source_cells={n:cs[n] for n in regs},ds=ds,initial=initial,resets=resets,replacements=replacements,added={EARLY:early,FLAG:ff},nets={EARLY+'$net':dict(hide_name=0,bits=[fresh],attributes={}),FLAG+'$D':dict(hide_name=0,bits=[fresh+1],attributes={})})

def miter(s):
 text=emit(s['old'],[*s['cuts'],241167],[s['oldout']],'gold')+'\n'
 text+=emit({EARLY:s['added'][EARLY],s['root']:s['replacements'][s['root']]},s['ds'],[s['added'][FLAG]['connections']['D'][0]],'next_predicate')+'\n'
 lines=['module proof(input clk,rst,input [7:0] d,output same);','wire [7:0] q;wire expected,fd,flag;']
 for i,n in enumerate(s['regs']):
  c=s['source_cells'][n];kind=c['attributes']['X_ORIG_TYPE'];sr='S' if kind=='FDSE' else 'R';init=c['parameters']['INIT'];lines.append(f"{kind} #(.INIT(1'b{init})) r{i}(.C(clk),.{sr}(rst),.CE(1'b1),.D(d[{i}]),.Q(q[{i}]));")
 lines.extend(["gold g({1'b0,q},expected);",'next_predicate next_g(d,fd);',"FDRE #(.INIT(1'b0)) f(.C(clk),.R(rst),.CE(1'b1),.D(fd),.Q(flag));",'assign same=flag==expected;','endmodule'])
 return text+'\n'.join(lines)+'\n'

def validate(patch,prior,base,gold):
 s=spec(base['modules']['top']);assert patch['timer_source_cells']==s['source_cells']
 expected={n:gold['modules']['top']['cells'][n] for n in [*s['old'],*s['regs'],'$PACKER_GND_DRV']}
 assert patch['original_cells']=={**prior['original_cells'],**expected}
 assert not set(s['replacements'])&set(prior['replacements'])
 for k,new in [('replacements',s['replacements']),('added_cells',s['added']),('added_netnames',s['nets'])]:assert patch[k]=={**prior[k],**new}
 for k in ['checkpoint','removed_cells','removed_netnames','added_latency_cycles']:assert patch[k]==prior[k]
 assert patch['added_latency_cycles']==0 and patch['redundant_timer_ff_added']==1
 assert set(patch['placements'])==set(prior['placements'])|{s['root'],EARLY,FLAG}
 for n,v in prior['placements'].items():assert patch['placements'][n]==v
 assert patch['placements'][s['root']].endswith('6LUT') and patch['placements'][FLAG]==patch['placements'][s['root']][:-4]+'FF'
 proof=patch['timer_proof'];assert Path(proof['miter']).read_text()==miter(s)
 for n,h in proof['sha256'].items():assert digest(n)==h,n
 assert 'Induction step proven: SUCCESS!' in Path(proof['log']).read_text()
 contract=Path(proof['packer_contract']).read_text();assert 'ce->name == vcc' in contract and 'disconnect_port(ctx, ci, id_CE);' in contract
 base['modules']['top']['cells'].update(copy.deepcopy(s['replacements']));base['modules']['top']['cells'].update(copy.deepcopy(s['added']));base['modules']['top']['netnames'].update(copy.deepcopy(s['nets']));return base

def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['timer_base_path']);assert digest(bp)==patch['timer_base_sha256'];prior=json.loads(bp.read_text());return validate(patch,prior,apply_base(prior,design),design)

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_same_edge_timer_mid_zero_flag',timer_base_path=str(bp),timer_base_sha256=digest(bp),timer_source_cells=s['source_cells'],redundant_timer_ff_added=1)
 patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [*s['old'],*s['regs'],'$PACKER_GND_DRV']})
 for k,new in [('replacements',s['replacements']),('added_cells',s['added']),('added_netnames',s['nets'])]:patch[k].update(new)
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n!=s['root']};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['SLICE_FFX','CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL'))}
 free={site:[l for l in 'ABCD' if all(site+'/'+l+t not in occupied for t in ['5LUT','6LUT','FF','5FF'])] for site in sites-bad};free={site:letters for site,letters in free.items() if len(letters)>=2};assert free
 def distance(site):
  x,y=map(int,re.search(r'SLICE_X(\d+)Y(\d+)',site).groups());return (abs(x-121)+abs(y-50),site)
 site=min(free,key=distance);l0,l1=free[site][:2];patch['placements'][EARLY]=site+'/'+l0+'6LUT';patch['placements'][s['root']]=site+'/'+l1+'6LUT';patch['placements'][FLAG]=site+'/'+l1+'FF'
 out.mkdir();v=out/'miter.v';v.write_text(miter(s));tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';contract=Path('build-grade2-refresher-flag-feasibility/packer-ce-contract.cc').resolve();ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -seq 4 -prove same 1 -verify\nsat -seq 3 -tempinduct -maxsteps 8 -prove same 1 -verify\n');log=out/'prove.log'
 with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 patch['timer_proof']=dict(miter=str(v),log=str(log),packer_contract=str(contract),sha256={str(q.resolve()):digest(q) for q in [v,ys,log,tool,lib,contract]});validate(patch,prior,base,gold);patch['sha256']=dict(prior['sha256']);patch['sha256'].update(patch['timer_proof']['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_zero_flag.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,added_redundant_ff=1,added_luts=1,old_mux_root_replaced_by_lut=True,added_latency_cycles=0,placement=site,actual_primitive_induction=True)))
if __name__=='__main__':main()
