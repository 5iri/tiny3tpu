#!/usr/bin/env python3
"""Factor the write-ID storage enable around late address and command controls."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_packed_read_response_vector import apply_verified as apply_base
from synapse32_packed_read_response_encoded_branch import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
from synapse32_apply_bram_timing import digest
CUTS=[49954,49986,49926,49956,138937,138938,138940]
EARLY=[49956,138940,138937,138938]
LATE={49954,49926}
def independent(cs):
    ls={n:logical(c) for n,c in cs.items() if (c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT')) or c['type']=='SELMUX2_1'};drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};memo={};active=set()
    def dep(b):
        if b in LATE:return True
        if b in memo:return memo[b]
        n=drv[b];c=cs[n]
        if n in ls:w,p,_=ls[n];ins=[p[f'I{i}'] for i in range(w)]
        elif c['type']=='CARRY4':ins=[b for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for b in bs]
        else:assert c['type'] in ['SLICE_FFX','PSEUDO_GND','PSEUDO_VCC','GND','VCC'],(n,c['type']);return False
        assert b not in active;active.add(b);v=any(dep(x) for x in ins);active.remove(b);memo[b]=v;return v
    assert not any(dep(b) for b in EARLY+[49986])
def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0;base=apply_base(patch['guard_base'],design);cs=base['modules']['top']['cells'];independent(cs);root=next(n for n in cs if n.endswith('$233727'));inner=next(n for n in cs if n.endswith('$228612'));assert patch['guard_root']==root and patch['guard_inner']==inner
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in patch['guard_base'][field].items():assert patch[field][n]==c
    name=patch['guard_cell'];assert set(patch['replacements'])==set(patch['guard_base']['replacements'])|{root};assert set(patch['added_cells'])==set(patch['guard_base']['added_cells'])|{name};assert set(patch['added_netnames'])==set(patch['guard_base']['added_netnames'])|{name+'$net'}
    guard=patch['added_cells'][name];w,gp,_=logical(guard);assert w==4 and [gp[f'I{i}'] for i in range(4)]==EARLY;oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs};assert gp['O'] not in oldbits;rp=logical(patch['replacements'][root])[1];assert rp['O']==logical(cs[root])[1]['O'];assert {v for k,v in rp.items() if k!='O'}<={gp['O'],49986,49926,49954}
    for word in range(128):
        vs={b:(word>>i)&1 for i,b in enumerate(CUTS)};expected=evaluate(cs[root],{**vs,logical(cs[inner])[1]['O']:evaluate(cs[inner],vs)});vs[gp['O']]=evaluate(guard,vs);assert evaluate(patch['replacements'][root],vs)==expected
    actual=copy.deepcopy(base);m=actual['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);cs=base['modules']['top']['cells'];independent(cs);root=next(n for n in cs if n.endswith('$233727'));inner=next(n for n in cs if n.endswith('$228612'));old=cs[root];assert not any(k.startswith('CONSTR_') for k in old['attributes']);patch=copy.deepcopy(prior);patch.pop('sha256');name='$tiny3tpu$write_id_early_guard';patch.update(kind='packed_write_id_guard',guard_base=prior,guard_cell=name,guard_root=root,guard_inner=inner)
    bit=max(b for c in cs.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1;mask=sum(int(bool(w&1) and bool(w&2) and not(bool(w&4) and bool(w&8)))<<w for w in range(16));patch['added_cells'][name]=packed(EARLY,bit,mask);patch['added_netnames'][name+'$net']=dict(hide_name=1,bits=[bit],attributes={})
    mask=sum(int(bool(w&1) and (bool(w&4) or (bool(w&2) and not bool(w&8))))<<w for w in range(16));new=packed([bit,49986,49926,49954],logical(old)[1]['O'],mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [root,inner]});patch['replacements'][root]=new
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    near=placed[root]['attributes']['NEXTPNR_BEL'];patch['placements'][root]=take(near);patch['placements'][name]=take(near);apply_verified(patch,gold);out.mkdir();miter=out/'miter.v';miter.write_text(emit({inner:cs[inner],root:cs[root]},CUTS,[logical(old)[1]['O']],'gold')+'\n'+emit({name:patch['added_cells'][name],root:new},CUTS,[logical(old)[1]['O']],'candidate')+'\nmodule proof(input [6:0] x,output same);wire [0:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {miter}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_read_response_vector.py'),yosys,lib,miter,script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print('PASS 128 guard cases and primitive SAT, composed with vector proof; zero added cycles')
if __name__=='__main__':main()
