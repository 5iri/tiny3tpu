"""Prove two DDR capture OR8 macros as two-LUT trees, preserving exact VCC provenance."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_ddr_read_valid_encoding import apply_verified as apply_base
from synapse32_packed_counter_encoding import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles']
SUFFIXES=['233944','233974']
def spec(m,suffix):
 NAME='$tiny3tpu$ddr_capture_or_'+suffix+'_early'
 cs=m['cells'];root=next(n for n,c in cs.items() if ('$'+suffix+'.') in n and c['attributes'].get('X_ORIG_TYPE')=='MUXF8');children=cs[root]['attributes']['CONSTR_CHILDREN'].split(';');assert len(children)==6
 ground=cs['$PACKER_VCC_DRV'];assert ground['type']=='PSEUDO_VCC';outs=[b for p,bs in ground['connections'].items() if ground['port_directions'][p]=='output' for b in bs];assert outs==[241169];g=outs[0]
 nodes={n:cs[n] for n in [root,*children]};outputs={logical(c)[1]['O'] for c in nodes.values()};inputs={b for c in nodes.values() for k,b in logical(c)[1].items() if k!='O'}-outputs;assert g in inputs;cuts=sorted(inputs-{g});assert len(cuts)==8
 available=set(inputs);order={};pending=dict(nodes)
 while pending:
  ready=[n for n,c in pending.items() if {b for k,b in logical(c)[1].items() if k!='O'}<=available];assert ready
  for n in ready:c=pending.pop(n);order[n]=c;available.add(logical(c)[1]['O'])
 for word in range(256):
  vs={b:(word>>i)&1 for i,b in enumerate(cuts)};vs[g]=1
  for c in order.values():vs[logical(c)[1]['O']]=evaluate(c,vs)
  assert vs[logical(cs[root])[1]['O']]==int(word!=0)
 late={'233944':[139456,139457],'233974':[139840,139841]}[suffix];assert set(late)<=set(cuts);early=[b for b in cuts if b not in late];bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']};fresh=max(b for b in bits if isinstance(b,int))+1
 added=packed(early,fresh,(1<<64)-2);new=packed([fresh,*late],logical(cs[root])[1]['O'],254);new['hide_name']=cs[root]['hide_name'];new['attributes'].update({k:v for k,v in cs[root]['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});replacements={root:new}
 for n in children:
  assert cs[n]['attributes']['CONSTR_PARENT']==root;v=copy.deepcopy(cs[n]);v['attributes']={k:v for k,v in v['attributes'].items() if not k.startswith('CONSTR_')};replacements[n]=v
 return dict(name=NAME,root=root,children=children,ground=g,cuts=cuts,old=order,added=added,net=dict(hide_name=1,bits=[fresh],attributes={}),replacements=replacements)

def install(m,s):
 m['cells'].update(copy.deepcopy(s['replacements']));m['cells'][s['name']]=copy.deepcopy(s['added']);m['netnames'][s['name']+'$net']=copy.deepcopy(s['net'])

def parent(patch):
 p=Path(patch['capture_or_base_path']);assert digest(p)==patch['capture_or_base_sha256'];return json.loads(p.read_text())

def apply_verified(patch,design):
 assert patch['passed'] and patch['added_latency_cycles']==0;prior=parent(patch);base=apply_base(prior,design);m=base['modules']['top'];targets=set();names=set()
 for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
 for field in ['replacements','added_cells','added_netnames']:
  for n,c in prior[field].items():assert patch[field][n]==c
 for suffix in SUFFIXES:
  s=spec(m,suffix);targets.update(s['replacements']);names.add(s['name']);assert patch['added_cells'][s['name']]==s['added'] and patch['added_netnames'][s['name']+'$net']==s['net']
  for n,c in s['replacements'].items():assert patch['replacements'][n]==c
  install(m,s)
 assert not targets&set(prior['replacements']);assert set(patch['replacements'])==set(prior['replacements'])|targets;assert set(patch['added_cells'])==set(prior['added_cells'])|names;assert set(patch['added_netnames'])==set(prior['added_netnames'])|{n+'$net' for n in names}
 return base

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());assert prior['passed']
 for n,h in prior['sha256'].items():assert digest(n)==h,n
 cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_ddr_capture_or_macros',capture_or_base_path=str(bp),capture_or_base_sha256=digest(bp));specs=[]
 for suffix in SUFFIXES:
  s=spec(m,suffix);specs.append(s);patch['replacements'].update(s['replacements']);patch['added_cells'][s['name']]=s['added'];patch['added_netnames'][s['name']+'$net']=s['net'];patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [*s['old'],'$PACKER_VCC_DRV']});install(m,s)
 reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';cs=json.loads(reference.read_text())['modules']['top']['cells'];occupied={patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']) for n,c in cs.items()}|set(patch['placements'].values());sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']).split('/')[0] for n,c in cs.items() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[site+'/'+l+'6LUT' for site in sites-bad for l in 'ABCD' if site+'/'+l+'5LUT' not in occupied and site+'/'+l+'6LUT' not in occupied]
 def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
 for s in specs:
  x,y=xy(cs[s['root']]['attributes']['NEXTPNR_BEL'])
  for name in [s['name'],s['root']]:
   bel=min(free,key=lambda b:(abs(xy(b)[0]-x)+abs(xy(b)[1]-y),b));free.remove(bel);patch['placements'][name]=bel
 out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';artifacts=[]
 for suffix,s in zip(SUFFIXES,specs):
  output=logical(s['old'][s['root']])[1]['O'];ov=emit(s['old'],[*s['cuts'],s['ground']],[output],'gold');nv=emit({s['name']:s['added'],s['root']:s['replacements'][s['root']]},s['cuts'],[output],'candidate');v=out/('miter-'+suffix+'.v');v.write_text(ov+'\n'+nv+"\nmodule proof(input [7:0] x,output same);wire a,b;gold g({1'b1,x},a);candidate c(x,b);assign same=a==b;endmodule\n");ys=out/('prove-'+suffix+'.ys');ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/('prove-'+suffix+'.log')
  with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
  assert 'SUCCESS!' in log.read_text();artifacts.extend([v,ys,log])
 apply_verified(patch,gold);patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_ddr_read_valid_encoding.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),tool,lib,*artifacts]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,exhaustive_cases=512,actual_primitive_sat=True,vcc_driver_exact=True,added_luts=2,added_latency_cycles=0)))
if __name__=='__main__':main()
