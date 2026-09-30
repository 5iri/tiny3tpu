#!/usr/bin/env python3
"""Encode shared main-enable control ahead of three late comparison/command inputs."""
import gc
gc.disable()
import argparse,copy,itertools,json,re,subprocess
from pathlib import Path
from synapse32_packed_uart_control_collapse import apply_verified as apply_base
from synapse32_packed_read_response_encoded_branch import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
from synapse32_apply_bram_timing import digest
LATE=[49926,49950,49954]
EARLY=[49956,49973,49986,105005,50435]
CUTS=LATE+EARLY

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
    assert not any(dep(b) for b in EARLY)

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0;base=apply_base(patch['ar_encoding_base'],design);cs=base['modules']['top']['cells'];independent(cs);root=next(n for n in cs if n.endswith('$233793'));inner='$tiny3tpu$ar_ready_enable_replica';assert patch['ar_encoding_root']==root and patch['ar_encoding_inner']==inner
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in patch['ar_encoding_base'][field].items():
            if field=='replacements' and n==root:continue
            assert patch[field][n]==c
    names=patch['ar_encoding_encoders'];assert len(names)==len(set(names))==2;assert set(patch['replacements'])==set(patch['ar_encoding_base']['replacements'])|{root};assert set(patch['added_cells'])==set(patch['ar_encoding_base']['added_cells'])|set(names);assert set(patch['added_netnames'])==set(patch['ar_encoding_base']['added_netnames'])|{n+'$net' for n in names}
    oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs};available=set(EARLY)
    for n in names:
        w,p,_=logical(patch['added_cells'][n]);assert {p[f'I{i}'] for i in range(w)}<=set(EARLY) and p['O'] not in oldbits|available;available.add(p['O'])
    rp=logical(patch['replacements'][root])[1];assert rp['O']==logical(cs[root])[1]['O'];assert {v for k,v in rp.items() if k!='O'}<=available|set(LATE)
    for word in range(256):
        vs={b:(word>>i)&1 for i,b in enumerate(CUTS)};expected=evaluate(cs[root],{**vs,logical(cs[inner])[1]['O']:evaluate(cs[inner],vs)})
        for n in names:vs[logical(patch['added_cells'][n])[1]['O']]=evaluate(patch['added_cells'][n],vs)
        assert evaluate(patch['replacements'][root],vs)==expected
    actual=copy.deepcopy(base);m=actual['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);cs=base['modules']['top']['cells'];independent(cs);root=next(n for n in cs if n.endswith('$233793'));inner='$tiny3tpu$ar_ready_enable_replica';old=cs[root];assert not any(k.startswith('CONSTR_') for k in old['attributes']);patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_main_ar_encoding_encoded',ar_encoding_base=prior,ar_encoding_root=root,ar_encoding_inner=inner,ar_encoding_encoders=[]);patterns=[]
    for word in range(32):
        pattern=0
        for state in range(8):
            vs={b:(word>>i)&1 for i,b in enumerate(EARLY)};vs.update({b:(state>>i)&1 for i,b in enumerate(LATE)});vs[logical(cs[inner])[1]['O']]=evaluate(cs[inner],vs);pattern|=evaluate(old,vs)<<state
        patterns.append(pattern)
    unique=sorted(set(patterns));assert unique==[0,170,187,255]
    def tables(codes):
        enc=dict(zip(unique,codes));return [[(enc[p]>>k)&1 for p in patterns] for k in range(2)]
    def support(t):return [i for i in range(5) if any(t[x]!=t[x^(1<<i)] for x in range(32))]
    choices=((0,)+c for c in itertools.permutations(range(1,4),3));codes=min(choices,key=lambda c:(sum(len(support(t)) for t in tables(c)),max(len(support(t)) for t in tables(c)),c));ts=tables(codes);fresh=max(b for c in cs.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1;encoded=[]
    for k,t in enumerate(ts):
        sup=support(t);assert sup;ins=[EARLY[i] for i in sup];truth=[t[sum(((x>>j)&1)<<i for j,i in enumerate(sup))] for x in range(1<<len(sup))];name=f'$tiny3tpu$main_ar_encoding_encoder_{k}';bit=fresh;fresh+=1;patch['added_cells'][name]=packed(ins,bit,sum(v<<i for i,v in enumerate(truth)));patch['added_netnames'][name+'$net']=dict(hide_name=1,bits=[bit],attributes={});patch['ar_encoding_encoders'].append(name);encoded.append(bit)
    inverse=dict(zip(codes,unique));mask=sum(((inverse.get(w&3,0)>>(w>>2))&1)<<w for w in range(32));new=packed(encoded+LATE,logical(old)[1]['O'],mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [root,inner] if n in gold['modules']['top']['cells']});patch['replacements'][root]=new
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    near=placed[root]['attributes']['NEXTPNR_BEL'];patch['placements'][root]=take(near)
    for n in patch['ar_encoding_encoders']:patch['placements'][n]=take(near)
    apply_verified(patch,gold);out.mkdir();miter=out/'miter.v';newcone={n:patch['added_cells'][n] for n in patch['ar_encoding_encoders']};newcone[root]=new;miter.write_text(emit({inner:cs[inner],root:old},CUTS,[logical(old)[1]['O']],'gold')+'\n'+emit(newcone,CUTS,[logical(old)[1]['O']],'candidate')+'\nmodule proof(input [7:0] x,output same);wire [0:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {miter}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_uart_control_collapse.py'),yosys,lib,miter,script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,cases=256,primitive_sat=True,code_assignment=codes,encoder_supports=[len(support(t)) for t in ts],added_latency_cycles=0)))
if __name__=='__main__':main()
