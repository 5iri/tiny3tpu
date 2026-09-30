"""Encode a DDR MUXF8 control macro using two early codes and a late LUT."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_all_bank_valid_collapse import apply_verified as apply_base
from synapse32_packed_counter_encoding import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles']
NAMES=['$tiny3tpu$ddr_read_valid_code0','$tiny3tpu$ddr_read_valid_code1']

def spec(m):
 cs=m['cells'];root=next(n for n,c in cs.items() if '$233977.' in n and c['attributes'].get('X_ORIG_TYPE')=='MUXF8');children=cs[root]['attributes']['CONSTR_CHILDREN'].split(';');assert len(children)==6
 ground=cs['$PACKER_GND_DRV'];assert ground['type']=='PSEUDO_GND';outs=[b for p,bs in ground['connections'].items() if ground['port_directions'][p]=='output' for b in bs];assert outs==[241167];g=outs[0]
 nodes={n:cs[n] for n in [root,*children]};outputs={logical(c)[1]['O'] for c in nodes.values()};inputs={b for c in nodes.values() for k,b in logical(c)[1].items() if k!='O'}-outputs;assert g in inputs;cuts=sorted(inputs-{g});assert len(cuts)==8
 available=set(inputs);order={};pending=dict(nodes)
 while pending:
  ready=[n for n,c in pending.items() if {b for k,b in logical(c)[1].items() if k!='O'}<=available];assert ready
  for n in ready:c=pending.pop(n);order[n]=c;available.add(logical(c)[1]['O'])
 truth=[]
 for word in range(256):
  vs={b:(word>>i)&1 for i,b in enumerate(cuts)};vs[g]=0
  for c in order.values():vs[logical(c)[1]['O']]=evaluate(c,vs)
  truth.append(vs[logical(cs[root])[1]['O']])
 late=[105590,105551,105571];assert set(late)<=set(cuts);early=[b for b in cuts if b not in late];assert len(early)==5
 functions=[]
 for e in range(32):
  f=0
  for l in range(8):
   vs={b:(e>>i)&1 for i,b in enumerate(early)}|{b:(l>>i)&1 for i,b in enumerate(late)}
   word=sum(vs[b]<<i for i,b in enumerate(cuts));f|=truth[word]<<l
  functions.append(f)
 assert sorted(set(functions))==[0,253,255];codes={0:0,253:1,255:3};decode={0:0,1:253,2:0,3:255}
 bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']};fresh=max(b for b in bits if isinstance(b,int))+1
 added={}
 for i,n in enumerate(NAMES):
  table=[(codes[f]>>i)&1 for f in functions];support=[j for j in range(5) if any(table[x]!=table[x^(1<<j)] for x in range(32))];ins=[early[j] for j in support];mask=sum(table[sum(((x>>k)&1)<<j for k,j in enumerate(support))]<<x for x in range(1<<len(support)));added[n]=packed(ins,fresh+i,mask)
 assert [logical(c)[0] for c in added.values()]==[5,3]
 nets={n+'$net':dict(hide_name=1,bits=[fresh+i],attributes={}) for i,n in enumerate(NAMES)}
 mask=sum(((decode[word&3]>>(word>>2))&1)<<word for word in range(32));new=packed([fresh,fresh+1,*late],logical(cs[root])[1]['O'],mask)
 for word in range(256):
  vs={b:(word>>i)&1 for i,b in enumerate(cuts)}
  for c in added.values():vs[logical(c)[1]['O']]=evaluate(c,vs)
  assert evaluate(new,vs)==truth[word]
 new['hide_name']=cs[root]['hide_name'];new['attributes'].update({k:v for k,v in cs[root]['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});replacements={root:new}
 for n in children:
  assert cs[n]['attributes']['CONSTR_PARENT']==root;v=copy.deepcopy(cs[n]);v['attributes']={k:v for k,v in v['attributes'].items() if not k.startswith('CONSTR_')};replacements[n]=v
 return dict(root=root,children=children,ground=g,cuts=cuts,old=order,added=added,nets=nets,replacements=replacements)

def parent(patch):
 p=Path(patch['read_valid_macro_base_path']);assert digest(p)==patch['read_valid_macro_base_sha256'];return json.loads(p.read_text())

def apply_verified(patch,design):
 assert patch['passed'] and patch['added_latency_cycles']==0;prior=parent(patch);base=apply_base(prior,design);s=spec(base['modules']['top']);assert patch['read_valid_macro_root']==s['root'] and patch['read_valid_macro_cuts']==s['cuts'];targets=set(s['replacements'])
 for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
 for field in ['replacements','added_cells','added_netnames']:
  for n,c in prior[field].items():assert patch[field][n]==c
 assert not targets&set(prior['replacements']);assert set(patch['replacements'])==set(prior['replacements'])|targets;assert set(patch['added_cells'])==set(prior['added_cells'])|set(NAMES);assert set(patch['added_netnames'])==set(prior['added_netnames'])|set(s['nets'])
 for n,c in s['added'].items():assert patch['added_cells'][n]==c
 for n,c in s['nets'].items():assert patch['added_netnames'][n]==c
 for n,c in s['replacements'].items():assert patch['replacements'][n]==c
 base['modules']['top']['cells'].update(copy.deepcopy(patch['replacements']));base['modules']['top']['cells'].update(copy.deepcopy(patch['added_cells']));base['modules']['top']['netnames'].update(copy.deepcopy(patch['added_netnames']));return base

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());assert prior['passed']
 for n,h in prior['sha256'].items():assert digest(n)==h,n
 cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_ddr_read_valid_macro',read_valid_macro_base_path=str(bp),read_valid_macro_base_sha256=digest(bp),read_valid_macro_root=s['root'],read_valid_macro_cuts=s['cuts']);patch['replacements'].update(s['replacements']);patch['added_cells'].update(s['added']);patch['added_netnames'].update(s['nets']);patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [*s['old'],'$PACKER_GND_DRV']})
 reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';cs=json.loads(reference.read_text())['modules']['top']['cells'];occupied={patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']) for n,c in cs.items()}|set(patch['placements'].values());sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']).split('/')[0] for n,c in cs.items() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[site+'/'+l+'6LUT' for site in sites-bad for l in 'ABCD' if site+'/'+l+'5LUT' not in occupied and site+'/'+l+'6LUT' not in occupied]
 def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
 for name,where in [(NAMES[0],(118,43)),(NAMES[1],(118,43)),(s['root'],(118,43))]:
  x,y=where;bel=min(free,key=lambda b:(abs(xy(b)[0]-x)+abs(xy(b)[1]-y),b));free.remove(bel);patch['placements'][name]=bel
 out.mkdir();ov=emit(s['old'],[*s['cuts'],s['ground']],[logical(s['old'][s['root']])[1]['O']],'gold');nv=emit({**s['added'],s['root']:s['replacements'][s['root']]},s['cuts'],[logical(s['old'][s['root']])[1]['O']],'candidate');v=out/'miter.v';v.write_text(ov+'\n'+nv+"\nmodule proof(input [7:0] x,output same);wire a,b;gold g({1'b0,x},a);candidate c(x,b);assign same=a==b;endmodule\n");tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/'prove.log'
 with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 assert 'SUCCESS!' in log.read_text();apply_verified(patch,gold);patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_all_bank_valid_collapse.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),tool,lib,v,ys,log]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,exhaustive_cases=256,actual_primitive_sat=True,ground_driver_exact=True,added_luts=2,added_latency_cycles=0)))
if __name__=='__main__':main()
