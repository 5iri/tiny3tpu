#!/usr/bin/env python3
"""Compose both DMA range-guard factorizations without state changes."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_selector_dma_guard import apply_verified as apply_base
from synapse32_packed_selector_encoded import discover
from synapse32_packed_selector_patch_v4 import logical,evaluate,packed,emit

def apply_verified(patch,design):
    base=apply_base(patch['base_patch'],design);cs=base['modules']['top']['cells'];names=patch['second_guard_cone'];root=names[-1];cone={n:cs[n] for n in names};outputs={logical(c)[1]['O'] for c in cone.values()};cuts=sorted({v for c in cone.values() for k,v in logical(c)[1].items() if k!='O'}-outputs);assert len(cuts)==12
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in patch['base_patch'][field].items():assert patch[field][n]==c
    assert set(patch['replacements'])==set(patch['base_patch']['replacements'])|{root};extra=set(patch['added_cells'])-set(patch['base_patch']['added_cells']);assert extra==set(patch['second_early_cells']) and len(extra)==2
    slow=set(patch['second_slow_inputs']);available=set(cuts)-slow;oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in base['modules']['top']['netnames'].values() for b in v['bits']}|{b for v in base['modules']['top']['ports'].values() for b in v['bits']}
    for n in patch['second_early_cells']:
        w,p,_=logical(patch['added_cells'][n]);assert {p[f'I{i}'] for i in range(w)}<=available and p['O'] not in oldbits|available;available.add(p['O'])
    assert logical(patch['replacements'][root])[1]['O']==logical(cs[root])[1]['O']
    for word in range(4096):
        vs={b:(word>>i)&1 for i,b in enumerate(cuts)};gold=vs.copy()
        for c in cone.values():gold[logical(c)[1]['O']]=evaluate(c,gold)
        for n in patch['second_early_cells']:
            c=patch['added_cells'][n];vs[logical(c)[1]['O']]=evaluate(c,vs)
        assert evaluate(patch['replacements'][root],vs)==gold[logical(cs[root])[1]['O']]
    actual=copy.deepcopy(base);m=actual['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();bp=a.base_patch.resolve();base=json.loads(bp.read_text());assert base['passed']
    for n,h in base['sha256'].items():assert digest(n)==h
    cp=Path(base['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());applied=apply_base(base,gold);cs=gold['modules']['top']['cells'];names=[next(n for n in cs if n.endswith('$'+s)) for s in ['224050','224049','224048']];root=names[-1];outputs={logical(cs[n])[1]['O'] for n in names};cuts=sorted({v for n in names for k,v in logical(cs[n])[1].items() if k!='O'}-outputs);assert len(cuts)==12;ones=[]
    for word in range(4096):
        vs={b:(word>>i)&1 for i,b in enumerate(cuts)}
        for n in names:vs[logical(cs[n])[1]['O']]=evaluate(cs[n],vs)
        if vs[logical(cs[root])[1]['O']]:ones.append(word)
    assert len(ones)==1;polarity={b:(ones[0]>>i)&1 for i,b in enumerate(cuts)};ip=logical(cs[names[0]])[1];slow=[ip[f'I{i}'] for i in range(2,6)];early=sorted(set(cuts)-set(slow));assert len(early)==8
    # Conservative graph dependency check, including all carry and mux inputs.
    drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};memo={};active=set()
    def dep(b):
        if b in slow:return True
        if b in memo:return memo[b]
        if b not in drv:return False
        c=cs[drv[b]]
        if c['type'] not in ['SLICE_LUTX','SELMUX2_1','CARRY4']:return False
        assert b not in active;active.add(b);v=any(dep(v) for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for v in bs);active.remove(b);memo[b]=v;return v
    assert not any(dep(b) for b in early)
    bit=max(b for c in applied['modules']['top']['cells'].values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1;ens=['$tiny3tpu$dma_bounds_early_0','$tiny3tpu$dma_bounds_early_1'];extras={ens[0]:packed(early[:6],bit,1<<sum(polarity[b]<<i for i,b in enumerate(early[:6]))),ens[1]:packed([bit]+early[6:],bit+1,1<<(1|sum(polarity[b]<<(i+1) for i,b in enumerate(early[6:]))))};new=packed(slow+[bit+1],logical(cs[root])[1]['O'],1<<(16|sum(polarity[b]<<i for i,b in enumerate(slow))));old=cs[root];assert not any(k.startswith('CONSTR_') for k in old['attributes']);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k!='X_ORIG_TYPE'})
    patch=copy.deepcopy(base);patch.pop('sha256');patch.update(kind='packed_selector_dma_dual_guard',base_patch=base,second_guard_cone=names,second_early_cells=ens,second_slow_inputs=slow);patch['original_cells'].update({n:cs[n] for n in names});patch['replacements'][root]=new;patch['added_cells'].update(extras)
    for i,n in enumerate(ens):patch['added_netnames'][n+'$net']=dict(hide_name=1,bits=[bit+i],attributes={})
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    patch['placements'][root]=take(placed[root]['attributes']['NEXTPNR_BEL'])
    for n in ens:patch['placements'][n]=take(placed[names[1]]['attributes']['NEXTPNR_BEL'])
    apply_verified(patch,gold);sn,_,cones,_=discover(cs);oldcone={k:v for c in cones.values() for k,v in c.items()};oldcone.update({n:cs[n] for n in base['guard_cone']+names});roots_names=sn+[base['guard_cone'][-1],root];newcone={**patch['added_cells'],**{n:patch['replacements'][n] for n in roots_names}};outputs={logical(c)[1]['O'] for c in oldcone.values()};leaves=sorted({v for c in oldcone.values() for k,v in logical(c)[1].items() if k!='O'}-outputs);roots=[logical(cs[n])[1]['O'] for n in roots_names];out.mkdir();(out/'miter.v').write_text(emit(oldcone,leaves,roots,'gold')+'\n'+emit(newcone,leaves,roots,'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire [17:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {out/"miter.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(base['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,Path(__file__),Path(__file__).with_name('synapse32_packed_selector_dma_guard.py'),yosys,lib,out/'miter.v',script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print('PASS 13312 cut cases and composed 18-output primitive SAT; zero added cycles')
if __name__=='__main__':main()
