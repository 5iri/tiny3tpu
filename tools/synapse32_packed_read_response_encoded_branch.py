#!/usr/bin/env python3
"""Exact cofactoring of the late DDR read-response selector cone."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import apply_verified as apply_base,logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed

SELECTORS={233964:105820,233965:105725,233967:105612,233968:105748,233969:105764,233970:105709,233972:105805,233973:105787}

def discover(m,selector):
    assert selector in SELECTORS
    cs=m['cells'];ls={n:logical(c) for n,c in cs.items() if (c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT')) or c['type']=='SELMUX2_1'};drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};rst=105590;root=next(n for n in ls if '$'+str(selector)+'.' in n and n.endswith('mux8'));memo={};active=set()
    def dep(b):
        if b==rst:return True
        if b in memo:return memo[b]
        if b not in drv:return False
        n=drv[b];c=cs[n]
        if n not in ls and c['type']!='CARRY4':return False
        assert b not in active;active.add(b);ins=[ls[n][1][f'I{i}'] for i in range(ls[n][0])] if n in ls else [v for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for v in bs];v=any(dep(v) for v in ins);active.remove(b);memo[b]=v;return v
    cone={};cuts=set()
    def walk(b):
        if b==rst or not dep(b):cuts.add(b);return
        n=drv[b];assert n in ls,('unsupported read_response-dependent primitive',n)
        if n in cone:return
        w,p,_=ls[n]
        for i in range(w):walk(p[f'I{i}'])
        cone[n]=cs[n]
    walk(ls[root][1]['O']);assert len(cuts)==10 and len(cone)==3;return root,rst,cone,sorted(cuts)

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0;base=apply_base(patch['base_patch'],design);m=base['modules']['top'];cs=m['cells'];root,rst,cone,cuts=discover(m,patch['selector_id']);assert patch['read_response_root']==root and patch['read_response_bit']==rst and patch['read_response_cuts']==cuts and patch['read_response_cone']==list(cone)
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in patch['base_patch'][field].items():assert patch[field][n]==c
    children=[n for n in cs[root]['attributes'].get('CONSTR_CHILDREN','').split(';') if n];assert set(patch['replacements'])==set(patch['base_patch']['replacements'])|{root}|set(children);
    for n in children:
        expected=copy.deepcopy(cs[n]);expected['attributes']={k:v for k,v in expected['attributes'].items() if not k.startswith('CONSTR_')};assert patch['replacements'][n]==expected
    extras=set(patch['added_cells'])-set(patch['base_patch']['added_cells']);assert extras==set(patch['read_response_early_cells']);available=set(cuts)-{rst,SELECTORS[patch['selector_id']]};oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']}
    for n in patch['read_response_early_cells']:
        w,p,_=logical(patch['added_cells'][n]);assert {p[f'I{i}'] for i in range(w)}<=available and p['O'] not in oldbits|available;available.add(p['O'])
    assert logical(patch['replacements'][root])[1]['O']==logical(cs[root])[1]['O']
    for word in range(1024):
        values={b:(word>>i)&1 for i,b in enumerate(cuts)};gold=values.copy()
        for c in cone.values():gold[logical(c)[1]['O']]=evaluate(c,gold)
        for n in patch['read_response_early_cells']:
            c=patch['added_cells'][n];values[logical(c)[1]['O']]=evaluate(c,values)
        assert evaluate(patch['replacements'][root],values)==gold[logical(cs[root])[1]['O']]
    actual=copy.deepcopy(base);am=actual['modules']['top'];am['cells'].update(copy.deepcopy(patch['replacements']));am['cells'].update(copy.deepcopy(patch['added_cells']));am['netnames'].update(copy.deepcopy(patch['added_netnames']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--selector',type=int,choices=sorted(SELECTORS),required=True);p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];cs=m['cells'];root,rst,cone,cuts=discover(m,a.selector);patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_read_response_choice',selector_id=a.selector,base_patch=prior,read_response_root=root,read_response_bit=rst,read_response_cone=list(cone),read_response_cuts=cuts,read_response_early_cells=[]);fresh=max(b for c in cs.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1;cache={};co=[]
    fresh+=100*sorted(SELECTORS).index(a.selector);late=[rst,SELECTORS[a.selector]];assert set(late)<=set(cuts);early=[b for b in cuts if b not in late];patterns=[]
    for word in range(1<<len(early)):
        pattern=0
        for state in range(4):
            vals={b:(word>>i)&1 for i,b in enumerate(early)};vals.update({b:(state>>i)&1 for i,b in enumerate(late)})
            for c in cone.values():vals[logical(c)[1]['O']]=evaluate(c,vals)
            pattern|=vals[logical(cs[root])[1]['O']]<<state
        patterns.append(pattern)
    unique=sorted(set(patterns));assert unique==[0,12,13,15];codes=dict(zip(unique,[0,1,3,2]));co=[]
    for k in range(2):
        truth=[(codes[v]>>k)&1 for v in patterns];support=[i for i in range(len(early)) if any(truth[x]!=truth[x^(1<<i)] for x in range(len(truth)))];ins=[early[i] for i in support];assert len(ins)==6
        reduced=[truth[sum(((x>>j)&1)<<i for j,i in enumerate(support))] for x in range(1<<len(support))];an=f'$tiny3tpu$read_response_{a.selector}_early_{k}';bit=fresh;fresh+=1;patch['added_cells'][an]=packed(ins,bit,sum(v<<i for i,v in enumerate(reduced)));patch['added_netnames'][an+'$net']=dict(hide_name=1,bits=[bit],attributes={});patch['read_response_early_cells'].append(an);co.append(bit)
    inverse={v:k for k,v in codes.items()};final_mask=sum(((inverse[word&3]>>(word>>2))&1)<<word for word in range(16))
    old=cs[root];assert 'CONSTR_PARENT' not in old['attributes'];
    for child in old['attributes'].get('CONSTR_CHILDREN','').split(';'):
        if not child:continue
        assert cs[child]['attributes']['CONSTR_PARENT']==root
        patch['original_cells'][child]=gold['modules']['top']['cells'][child];patch['replacements'][child]=copy.deepcopy(cs[child]);patch['replacements'][child]['attributes']={k:v for k,v in cs[child]['attributes'].items() if not k.startswith('CONSTR_')}
    new=packed(co+late,logical(old)[1]['O'],final_mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in cone});patch['replacements'][root]=new
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    near=placed[root]['attributes']['NEXTPNR_BEL'];patch['placements'][root]=take(near)
    for n in patch['read_response_early_cells']:patch['placements'][n]=take(near)
    apply_verified(patch,gold);out.mkdir();newcone={n:patch['added_cells'][n] for n in patch['read_response_early_cells']};newcone[root]=new;roots=[logical(cs[root])[1]['O']];(out/'miter.v').write_text(emit(cone,cuts,roots,'gold')+'\n'+emit(newcone,cuts,roots,'candidate')+f'\nmodule proof(input [{len(cuts)-1}:0] x,output same);wire [0:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {out/"miter.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),yosys,lib,out/'miter.v',script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print(json.dumps(dict(passed=True,read_response_cases=1024,added_read_response_luts=len(patch['read_response_early_cells']),actual_primitive_sat=True,added_latency_cycles=0)))
if __name__=='__main__':main()
