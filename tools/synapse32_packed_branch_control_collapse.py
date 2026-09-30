#!/usr/bin/env python3
"""Collapse two CPU branch-control LUTs into one exact LUT6, without state changes."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_transport_reset_choice import apply_verified as apply_base,logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed

def cone(cs):
    root=next(n for n in cs if n.endswith('$221081'));inner=next(n for n in cs if n.endswith('$220968'))
    rp=logical(cs[root])[1];ip=logical(cs[inner])[1]
    assert ip['O'] in [v for k,v in rp.items() if k!='O']
    leaves=sorted(({v for k,v in rp.items() if k!='O'}|{v for k,v in ip.items() if k!='O'})-{ip['O']})
    assert len(leaves)==6 and rp['O'] not in leaves
    return root,inner,leaves

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0
    base=apply_base(patch['branch_base'],design);cs=base['modules']['top']['cells'];root,inner,leaves=cone(cs)
    assert patch['branch_root']==root and patch['branch_inner']==inner and patch['branch_cuts']==leaves
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['added_cells','added_netnames']:assert patch[field]==patch['branch_base'][field]
    assert set(patch['replacements'])==set(patch['branch_base']['replacements'])|{root}
    for n,c in patch['branch_base']['replacements'].items():assert patch['replacements'][n]==c
    new=patch['replacements'][root];w,p,_=logical(new)
    assert w==6 and [p[f'I{i}'] for i in range(w)]==leaves and p['O']==logical(cs[root])[1]['O']
    for word in range(64):
        vs={b:(word>>i)&1 for i,b in enumerate(leaves)}
        expected=evaluate(cs[root],{**vs,logical(cs[inner])[1]['O']:evaluate(cs[inner],vs)})
        assert evaluate(new,vs)==expected
    result=copy.deepcopy(base);result['modules']['top']['cells'].update(copy.deepcopy(patch['replacements']));return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists()
    prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);cs=base['modules']['top']['cells'];root,inner,leaves=cone(cs)
    mask=0
    for word in range(64):
        vs={b:(word>>i)&1 for i,b in enumerate(leaves)};mask|=evaluate(cs[root],{**vs,logical(cs[inner])[1]['O']:evaluate(cs[inner],vs)})<<word
    patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_branch_control_collapse',branch_base=prior,branch_root=root,branch_inner=inner,branch_cuts=leaves)
    old=cs[root];assert not any(k.startswith('CONSTR_') for k in old['attributes']);new=packed(leaves,logical(old)[1]['O'],mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']})
    patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [root,inner]});patch['replacements'][root]=new
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'}
    free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    x,y=xy(placed[root]['attributes']['NEXTPNR_BEL']);patch['placements'][root]=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v))
    apply_verified(patch,gold);out.mkdir();miter=out/'miter.v';miter.write_text(emit({inner:cs[inner],root:cs[root]},leaves,[logical(old)[1]['O']],'gold')+'\n'+emit({root:new},leaves,[logical(old)[1]['O']],'candidate')+'\nmodule proof(input [5:0] x,output same);wire [0:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {miter}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_transport_reset_choice.py'),yosys,lib,miter,script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,cases=64,primitive_sat=True,added_latency_cycles=0)))
if __name__=='__main__':main()
