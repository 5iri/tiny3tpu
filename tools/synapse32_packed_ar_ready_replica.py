#!/usr/bin/env python3
"""Replicate an identical shared enable decode beside the AR-ready consumer."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_packed_main_ce_encoded import apply_verified as apply_base
from synapse32_packed_read_response_encoded_branch import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
from synapse32_apply_bram_timing import digest

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0;base=apply_base(patch['replica_base'],design);cs=base['modules']['top']['cells'];source=next(n for n in cs if n.endswith('$217104'));root=next(n for n in cs if n.endswith('$233793'));assert patch['replica_source']==source and patch['replica_consumer']==root;name=patch['replica_cell']
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in patch['replica_base'][field].items():assert patch[field][n]==c
    assert set(patch['replacements'])==set(patch['replica_base']['replacements'])|{root};assert set(patch['added_cells'])==set(patch['replica_base']['added_cells'])|{name};assert set(patch['added_netnames'])==set(patch['replica_base']['added_netnames'])|{name+'$net'}
    w,p,mask=logical(cs[source]);cw,cp,cm=logical(patch['added_cells'][name]);assert cw==w and cm==mask and all(cp[f'I{i}']==p[f'I{i}'] for i in range(w));fresh=cp['O'];oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs};assert fresh not in oldbits
    expected=copy.deepcopy(cs[root]);ports=[k for k,bs in expected['connections'].items() if bs==[p['O']] and expected['port_directions'][k]=='input'];assert len(ports)==1;expected['connections'][ports[0]]=[fresh];assert patch['replacements'][root]==expected;assert patch['added_netnames'][name+'$net']['bits']==[fresh]
    roots=[logical(cs[root])[1]['O']];leaves=sorted(({v for k,v in p.items() if k!='O'}|{v for k,v in logical(cs[root])[1].items() if k!='O'})-{p['O']});assert len(leaves)<=10
    for word in range(1<<len(leaves)):
        vs={b:(word>>i)&1 for i,b in enumerate(leaves)};oldvs={**vs,p['O']:evaluate(cs[source],vs)};newvs={**vs,fresh:evaluate(patch['added_cells'][name],vs)};assert evaluate(cs[root],oldvs)==evaluate(expected,newvs)
    result=copy.deepcopy(base);m=result['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source_path=cp.parent/'pre-fixup.json';gold=json.loads(source_path.read_text());base=apply_base(prior,gold);cs=base['modules']['top']['cells'];source=next(n for n in cs if n.endswith('$217104'));root=next(n for n in cs if n.endswith('$233793'));w,p,mask=logical(cs[source]);assert w==6;name='$tiny3tpu$ar_ready_enable_replica';fresh=max(b for c in cs.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1;patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_ar_ready_replica',replica_base=prior,replica_source=source,replica_consumer=root,replica_cell=name);patch['added_cells'][name]=packed([p[f'I{i}'] for i in range(w)],fresh,mask);patch['added_netnames'][name+'$net']=dict(hide_name=1,bits=[fresh],attributes={});new=copy.deepcopy(cs[root]);ports=[k for k,bs in new['connections'].items() if bs==[p['O']] and new['port_directions'][k]=='input'];assert len(ports)==1;new['connections'][ports[0]]=[fresh];patch['replacements'][root]=new;patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [source,root]})
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    x,y=xy(placed[root]['attributes']['NEXTPNR_BEL']);patch['placements'][name]=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));apply_verified(patch,gold);leaves=sorted(({v for k,v in p.items() if k!='O'}|{v for k,v in logical(cs[root])[1].items() if k!='O'})-{p['O']});out.mkdir();miter=out/'miter.v';miter.write_text(emit({source:cs[source],root:cs[root]},leaves,[logical(cs[root])[1]['O']],'gold')+'\n'+emit({name:patch['added_cells'][name],root:new},leaves,[logical(cs[root])[1]['O']],'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire [0:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {miter}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source_path,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_main_ce_encoded.py'),yosys,lib,miter,script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print(json.dumps(dict(passed=True,cases=1<<len(leaves),primitive_sat=True,added_luts=1,added_latency_cycles=0,replica_bel=patch['placements'][name])))
if __name__=='__main__':main()
