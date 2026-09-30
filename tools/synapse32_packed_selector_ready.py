#!/usr/bin/env python3
"""Compose proved selector encoding with an exact DDR AW-ready LUT collapse."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_selector_encoded import apply_verified as apply_selector,discover
from synapse32_packed_selector_patch_v4 import logical,evaluate,packed,emit

def apply_verified(patch,design):
    base=apply_selector(patch['selector_patch'],design);cs=base['modules']['top']['cells'];root=patch['ready_root'];inner=patch['ready_inner'];rp=logical(cs[root])[1];ip=logical(cs[inner])[1];leaves=sorted(({v for k,v in rp.items() if k!='O'}|{v for k,v in ip.items() if k!='O'})-{ip['O']});assert len(leaves)==6
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    assert patch['added_cells']==patch['selector_patch']['added_cells'] and patch['added_netnames']==patch['selector_patch']['added_netnames']
    for n,c in patch['selector_patch']['replacements'].items():assert patch['replacements'][n]==c
    assert logical(patch['replacements'][root])[1]['O']==rp['O']
    for word in range(64):
        vs={b:(word>>i)&1 for i,b in enumerate(leaves)};expected=evaluate(cs[root],{**vs,ip['O']:evaluate(cs[inner],vs)});assert evaluate(patch['replacements'][root],vs)==expected
    for n in set(patch['replacements'])-set(patch['selector_patch']['replacements'])-{root}:
        a=copy.deepcopy(cs[n]);b=copy.deepcopy(patch['replacements'][n]);assert a['type']=='SLICE_FFX'
        for c in [a,b]:c['attributes']={k:v for k,v in c['attributes'].items() if not k.startswith('CONSTR_')}
        assert a==b
    actual=copy.deepcopy(base);actual['modules']['top']['cells'].update(copy.deepcopy(patch['replacements']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--selector-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();sp=a.selector_patch.resolve();sel=json.loads(sp.read_text());assert sel['passed']
    for n,h in sel['sha256'].items():assert digest(n)==h
    cp=Path(sel['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());apply_selector(sel,gold);cs=gold['modules']['top']['cells'];root=next(n for n in cs if n.endswith('$233791'));inner=next(n for n in cs if n.endswith('$228612'));rp=logical(cs[root])[1];ip=logical(cs[inner])[1];leaves=sorted(({v for k,v in rp.items() if k!='O'}|{v for k,v in ip.items() if k!='O'})-{ip['O']});assert len(leaves)==6
    mask=0
    for word in range(64):
        vs={b:(word>>i)&1 for i,b in enumerate(leaves)};mask|=evaluate(cs[root],{**vs,ip['O']:evaluate(cs[inner],vs)})<<word
    patch=copy.deepcopy(sel);patch.pop('sha256');patch.update(kind='packed_selector_encoding_ready_collapse',selector_patch=sel,ready_root=root,ready_inner=inner);old=cs[root];new=packed(leaves,rp['O'],mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k!='X_ORIG_TYPE'});patch['original_cells'][root]=old;patch['replacements'][root]=new;assert 'CONSTR_PARENT' not in old['attributes']
    for child in old['attributes'].get('CONSTR_CHILDREN','').split(';'):
        if not child:continue
        assert cs[child]['type']=='SLICE_FFX' and cs[child]['attributes']['CONSTR_PARENT']==root;patch['original_cells'][child]=cs[child];patch['replacements'][child]=copy.deepcopy(cs[child]);patch['replacements'][child]['attributes']={k:v for k,v in patch['replacements'][child]['attributes'].items() if not k.startswith('CONSTR_')}
    check=json.loads(cp.read_text());reference=Path(check['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'}
    free=[site+'/'+letter+'6LUT' for site in sites-bad for letter in 'ABCD' if site+'/'+letter+'5LUT' not in occupied and site+'/'+letter+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    near=placed[root]['attributes']['NEXTPNR_BEL'];x,y=xy(near);patch['placements'][root]=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));apply_verified(patch,gold)
    names,late,cones,cuts=discover(cs);oldcone={k:v for cone in cones.values() for k,v in cone.items()};oldcone.update({inner:cs[inner],root:cs[root]});newcone={**patch['added_cells'],**{n:patch['replacements'][n] for n in names+[root]}};outputs={logical(c)[1]['O'] for c in oldcone.values()};leaves=sorted({v for c in oldcone.values() for k,v in logical(c)[1].items() if k!='O'}-outputs);roots=[logical(cs[n])[1]['O'] for n in names+[root]];out.mkdir();(out/'miter.v').write_text(emit(oldcone,leaves,roots,'gold')+'\n'+emit(newcone,leaves,roots,'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire [16:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {out/"miter.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(sel['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [sp,Path(__file__),Path(__file__).with_name('synapse32_packed_selector_encoded.py'),yosys,lib,out/'miter.v',script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print('PASS 8192 selector cases, 64 ready cases, and composed 17-output primitive SAT; zero added cycles')
if __name__=='__main__':main()
