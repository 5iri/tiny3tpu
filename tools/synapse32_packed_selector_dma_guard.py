#!/usr/bin/env python3
"""Compose selector encoding with an exact late DMA range-guard factoring."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_selector_encoded import apply_verified as apply_selector,discover
from synapse32_packed_selector_patch_v4 import logical,evaluate,packed,emit

def apply_verified(patch,design):
    base=apply_selector(patch['selector_patch'],design);cs=base['modules']['top']['cells'];names=patch['guard_cone'];cone={n:cs[n] for n in names};root=names[-1];outputs={logical(c)[1]['O'] for c in cone.values()};leaves=sorted({v for c in cone.values() for k,v in logical(c)[1].items() if k!='O'}-outputs);assert len(leaves)==10
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for n,c in patch['selector_patch']['replacements'].items():assert patch['replacements'][n]==c
    for n,c in patch['selector_patch']['added_cells'].items():assert patch['added_cells'][n]==c
    for n,c in patch['selector_patch']['added_netnames'].items():assert patch['added_netnames'][n]==c
    extra=set(patch['added_cells'])-set(patch['selector_patch']['added_cells']);assert extra=={patch['early_guard']};early=patch['added_cells'][patch['early_guard']];ep=logical(early)[1];late={v for k,v in logical(cs[names[0]])[1].items() if k!='O'};assert not ({v for k,v in ep.items() if k!='O'}&late)
    oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in base['modules']['top']['netnames'].values() for b in v['bits']}|{b for v in base['modules']['top']['ports'].values() for b in v['bits']};assert ep['O'] not in oldbits
    assert logical(patch['replacements'][root])[1]['O']==logical(cs[root])[1]['O']
    for word in range(1<<len(leaves)):
        vs={b:(word>>i)&1 for i,b in enumerate(leaves)};expected=vs.copy()
        for c in cone.values():expected[logical(c)[1]['O']]=evaluate(c,expected)
        vs[ep['O']]=evaluate(early,vs);assert evaluate(patch['replacements'][root],vs)==expected[logical(cs[root])[1]['O']]
    assert set(patch['replacements'])==set(patch['selector_patch']['replacements'])|{root}
    actual=copy.deepcopy(base);m=actual['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--selector-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();sp=a.selector_patch.resolve();sel=json.loads(sp.read_text());assert sel['passed']
    for n,h in sel['sha256'].items():assert digest(n)==h
    cp=Path(sel['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_selector(sel,gold);cs=gold['modules']['top']['cells'];names=[next(n for n in cs if n.endswith('$'+s)) for s in ['224047','224043','224042']];inner,middle,root=names;ip=logical(cs[inner])[1];mp=logical(cs[middle])[1];rp=logical(cs[root])[1];assert logical(cs[inner])[0]==4 and logical(cs[middle])[0]==6 and logical(cs[root])[0]==2
    early_inputs=sorted(({v for k,v in mp.items() if k!='O'}|{v for k,v in rp.items() if k!='O'})-{ip['O'],mp['O']});assert len(early_inputs)==6
    # The two following gates are zero whenever the inner predicate is zero.
    mask=0
    for word in range(64):
        vs={b:(word>>i)&1 for i,b in enumerate(early_inputs)}
        for value in [0,1]:
            x={**vs,ip['O']:value};x[mp['O']]=evaluate(cs[middle],x);v=evaluate(cs[root],x)
            if value==0:assert v==0
            else:mask|=v<<word
    bit=max(b for c in base['modules']['top']['cells'].values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1;en='$tiny3tpu$dma_range_early_guard';early=packed(early_inputs,bit,mask);late=[ip[f'I{i}'] for i in range(4)];finalmask=sum((evaluate(cs[inner],{b:(w>>i)&1 for i,b in enumerate(late)})&((w>>4)&1))<<w for w in range(32));new=packed(late+[bit],rp['O'],finalmask);old=cs[root];assert not any(k.startswith('CONSTR_') for k in old['attributes']);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k!='X_ORIG_TYPE'})
    patch=copy.deepcopy(sel);patch.pop('sha256');patch.update(kind='packed_selector_dma_guard',selector_patch=sel,guard_cone=names,early_guard=en);patch['original_cells'].update({n:cs[n] for n in names});patch['replacements'][root]=new;patch['added_cells'][en]=early;patch['added_netnames'][en+'$net']=dict(hide_name=1,bits=[bit],attributes={})
    check=json.loads(cp.read_text());reference=Path(check['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'}
    free=[site+'/'+letter+'6LUT' for site in sites-bad for letter in 'ABCD' if site+'/'+letter+'5LUT' not in occupied and site+'/'+letter+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    patch['placements'][root]=take(placed[root]['attributes']['NEXTPNR_BEL']);patch['placements'][en]=take(placed[middle]['attributes']['NEXTPNR_BEL']);apply_verified(patch,gold)
    sn,_,cones,_=discover(cs);oldcone={k:v for cone in cones.values() for k,v in cone.items()};oldcone.update({n:cs[n] for n in names});newcone={**patch['added_cells'],**{n:patch['replacements'][n] for n in sn+[root]}};outputs={logical(c)[1]['O'] for c in oldcone.values()};leaves=sorted({v for c in oldcone.values() for k,v in logical(c)[1].items() if k!='O'}-outputs);roots=[logical(cs[n])[1]['O'] for n in sn+[root]];out.mkdir();(out/'miter.v').write_text(emit(oldcone,leaves,roots,'gold')+'\n'+emit(newcone,leaves,roots,'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire [16:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {out/"miter.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(sel['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [sp,Path(__file__),Path(__file__).with_name('synapse32_packed_selector_encoded.py'),yosys,lib,out/'miter.v',script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print('PASS 8192 selector cases, 1024 DMA guard cases, composed 17-output primitive SAT; zero added cycles')
if __name__=='__main__':main()
