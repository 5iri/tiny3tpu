#!/usr/bin/env python3
"""Exact cofactoring of the late reset cone feeding DMA output FIFO write enable."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_ar_ready_replica import apply_verified as apply_base,logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed

def discover(m):
    cs=m['cells'];ls={n:logical(c) for n,c in cs.items() if (c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT')) or c['type']=='SELMUX2_1'};drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};rst=m['netnames']['rst']['bits'][0];root=next(n for n in ls if n.endswith('$234649'));memo={};active=set()
    def dep(b):
        if b==rst:return True
        if b in memo:return memo[b]
        assert b in drv,('undriven cut',b)
        n=drv[b];c=cs[n]
        if n not in ls and c['type']!='CARRY4':
            assert c['type'] in ['SLICE_FFX','PSEUDO_GND','PSEUDO_VCC','GND','VCC'],(n,c['type']);return False
        assert b not in active;active.add(b);ins=[ls[n][1][f'I{i}'] for i in range(ls[n][0])] if n in ls else [v for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for v in bs];v=any(dep(v) for v in ins);active.remove(b);memo[b]=v;return v
    cone={};cuts=set()
    def walk(b):
        if b==rst or not dep(b):cuts.add(b);return
        n=drv[b];assert n in ls,('unsupported reset-dependent primitive',n)
        if n in cone:return
        w,p,_=ls[n]
        for i in range(w):walk(p[f'I{i}'])
        cone[n]=cs[n]
    walk(ls[root][1]['O']);assert len(cuts)==13 and len(cone)==5;return root,rst,cone,sorted(cuts)

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0;base=apply_base(patch['base_patch'],design);m=base['modules']['top'];cs=m['cells'];root,rst,cone,cuts=discover(m);assert patch['reset_root']==root and patch['reset_bit']==rst and patch['reset_cuts']==cuts and patch['reset_cone']==list(cone)
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in patch['base_patch'][field].items():assert patch[field][n]==c
    assert set(patch['replacements'])==set(patch['base_patch']['replacements'])|{root};extras=set(patch['added_cells'])-set(patch['base_patch']['added_cells']);assert extras==set(patch['reset_early_cells']);available=set(cuts)-{rst};oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']}
    for n in patch['reset_early_cells']:
        w,p,_=logical(patch['added_cells'][n]);assert {p[f'I{i}'] for i in range(w)}<=available and p['O'] not in oldbits|available;available.add(p['O'])
    assert logical(patch['replacements'][root])[1]['O']==logical(cs[root])[1]['O']
    for word in range(8192):
        values={b:(word>>i)&1 for i,b in enumerate(cuts)};gold=values.copy()
        for c in cone.values():gold[logical(c)[1]['O']]=evaluate(c,gold)
        for n in patch['reset_early_cells']:
            c=patch['added_cells'][n];values[logical(c)[1]['O']]=evaluate(c,values)
        assert evaluate(patch['replacements'][root],values)==gold[logical(cs[root])[1]['O']]
    actual=copy.deepcopy(base);am=actual['modules']['top'];am['cells'].update(copy.deepcopy(patch['replacements']));am['cells'].update(copy.deepcopy(patch['added_cells']));am['netnames'].update(copy.deepcopy(patch['added_netnames']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];cs=m['cells'];root,rst,cone,cuts=discover(m);patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_fifo_reset_choice',base_patch=prior,reset_root=root,reset_bit=rst,reset_cone=list(cone),reset_cuts=cuts,reset_early_cells=[]);fresh=max(b for c in cs.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1;cache={};co=[]
    for rv in [0,1]:
        sub={rst:('constant',rv)}
        for n,c in cone.items():
            w,p,_=logical(c);mapped={p[f'I{i}']:sub.get(p[f'I{i}'],p[f'I{i}']) for i in range(w)};ins=list(dict.fromkeys(v for v in mapped.values() if isinstance(v,int)));truth=[]
            for word in range(1<<len(ins)):
                vs={b:(word>>i)&1 for i,b in enumerate(ins)};original={b:(v[1] if isinstance(v,tuple) else vs[v]) for b,v in mapped.items()};truth.append(evaluate(c,original))
            support=[i for i in range(len(ins)) if any(truth[x]!=truth[x^(1<<i)] for x in range(len(truth)))];values=[truth[sum(((x>>j)&1)<<i for j,i in enumerate(support))] for x in range(1<<len(support))];ins=[ins[i] for i in support];mask=sum(v<<i for i,v in enumerate(values));outbit=p['O']
            if not ins:sub[outbit]=('constant',mask);continue
            if len(ins)==1 and mask==2:sub[outbit]=ins[0];continue
            key=(tuple(ins),mask)
            if key in cache:sub[outbit]=cache[key];continue
            an=f'$tiny3tpu$fifo_reset_choice_early_{len(patch["reset_early_cells"])}';bit=fresh;fresh+=1;patch['added_cells'][an]=packed(ins,bit,mask);patch['added_netnames'][an+'$net']=dict(hide_name=1,bits=[bit],attributes={});patch['reset_early_cells'].append(an);cache[key]=bit;sub[outbit]=bit
        result=sub[logical(cs[root])[1]['O']];co.append(result)
    final_ins=list(dict.fromkeys([v for v in co if isinstance(v,int)]+[rst]));final_mask=0
    for word in range(1<<len(final_ins)):
        vals={b:(word>>i)&1 for i,b in enumerate(final_ins)};value=co[vals[rst]];final_mask|=(value[1] if isinstance(value,tuple) else vals[value])<<word
    # Remove cofactor nodes which became unobservable after constant folding.
    byout={logical(patch['added_cells'][n])[1]['O']:n for n in patch['reset_early_cells']};needed=set()
    def need(b):
        if b not in byout:return
        n=byout[b]
        if n in needed:return
        needed.add(n);w,p,_=logical(patch['added_cells'][n])
        for i in range(w):need(p[f'I{i}'])
    for b in final_ins:need(b)
    for n in patch['reset_early_cells'][:]:
        if n not in needed:del patch['added_cells'][n];del patch['added_netnames'][n+'$net'];patch['reset_early_cells'].remove(n)
    old=cs[root];assert not any(k.startswith('CONSTR_') for k in old['attributes']);new=packed(final_ins,logical(old)[1]['O'],final_mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in cone});patch['replacements'][root]=new
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    near=placed[root]['attributes']['NEXTPNR_BEL'];patch['placements'][root]=take(near)
    for n in patch['reset_early_cells']:patch['placements'][n]=take(near)
    apply_verified(patch,gold);out.mkdir();newcone={n:patch['added_cells'][n] for n in patch['reset_early_cells']};newcone[root]=new;roots=[logical(cs[root])[1]['O']];(out/'miter.v').write_text(emit(cone,cuts,roots,'gold')+'\n'+emit(newcone,cuts,roots,'candidate')+f'\nmodule proof(input [{len(cuts)-1}:0] x,output same);wire [0:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {out/"miter.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_ar_ready_replica.py'),yosys,lib,out/'miter.v',script,out/'prove.log']});(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print(json.dumps(dict(passed=True,reset_cases=8192,added_reset_luts=len(patch['reset_early_cells']),actual_primitive_sat=True,added_latency_cycles=0)))
if __name__=='__main__':main()
