#!/usr/bin/env python3
"""Exact three-control functional decomposition of the packed DDR selector bus."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_selector_patch_v4 import logical,evaluate,packed,emit

def discover(cells):
    ls={n:logical(c) for n,c in cells.items() if c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT')}
    drv={p['O']:n for n,(w,p,t) in ls.items()};shared=next(n for n in ls if n.endswith('$217011'));gp=ls[shared][1];late=[gp['I0'],gp['I1'],ls[next(n for n in ls if n.endswith('$217100'))][1]['O']];memo={};active=set()
    def dep(b):
        if b in late:return True
        if b in memo:return memo[b]
        if b not in drv:return False
        assert b not in active;active.add(b);w,p,_=ls[drv[b]];v=any(dep(p[f'I{i}']) for i in range(w));active.remove(b);memo[b]=v;return v
    targets=sorted(n for n,(w,p,_) in ls.items() if gp['O'] in [p[f'I{i}'] for i in range(w)])
    cones={};cuts={}
    for n in targets:
        cone={};leaves=set()
        def walk(b):
            if b in late or not dep(b):leaves.add(b);return
            k=drv[b]
            if k in cone:return
            w,p,_=ls[k]
            for i in range(w):walk(p[f'I{i}'])
            cone[k]=cells[k]
        walk(ls[n][1]['O']);cones[n]=cone;cuts[n]=sorted(leaves)
    assert len(targets)==16
    return targets,late,cones,cuts

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0
    cells=design['modules']['top']['cells'];names,late,cones,cuts=discover(cells)
    assert patch['late_inputs']==late and [v['name'] for v in patch['targets']]==names
    for n,c in patch['original_cells'].items():assert cells[n]==c
    assert not set(patch['added_cells'])&set(cells)
    oldbits={b for c in cells.values() for bs in c['connections'].values() for b in bs}|{b for v in design['modules']['top']['netnames'].values() for b in v['bits']}|{b for v in design['modules']['top']['ports'].values() for b in v['bits']}
    newbits=[logical(c)[1]['O'] for c in patch['added_cells'].values()];assert len(newbits)==len(set(newbits)) and not set(newbits)&oldbits
    assert not set(patch['added_netnames'])&set(design['modules']['top']['netnames'])
    for item in patch['targets']:
        n=item['name'];cone=cones[n];leaves=cuts[n];assert item['cuts']==leaves
        added={k:patch['added_cells'][k] for k in item['added']};root=patch['replacements'][n];assert logical(root)[1]['O']==logical(cells[n])[1]['O']
        # Each precomputed node may depend only on early cuts and preceding early nodes.
        available=set(leaves)-set(late)
        for c in added.values():
            w,p,_=logical(c);assert {p[f'I{i}'] for i in range(w)}<=available
            available.add(p['O'])
        for word in range(1<<len(leaves)):
            values={b:(word>>i)&1 for i,b in enumerate(leaves)};gold=values.copy()
            for c in cone.values():gold[logical(c)[1]['O']]=evaluate(c,gold)
            for c in added.values():values[logical(c)[1]['O']]=evaluate(c,values)
            assert evaluate(root,values)==gold[logical(root)[1]['O']]
    for n in set(patch['replacements'])-set(names):
        a=copy.deepcopy(cells[n]);b=copy.deepcopy(patch['replacements'][n]);assert a['type']=='SLICE_FFX'
        for c in [a,b]:c['attributes']={k:v for k,v in c['attributes'].items() if not k.startswith('CONSTR_')}
        assert a==b
    actual=copy.deepcopy(design);m=actual['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();cp=a.checkpoint.resolve();out=a.out.resolve();assert not out.exists();manifest=cp/'manifest.json';check=json.loads(manifest.read_text());assert check['passed'] and check['routed_json_exact']
    for k in ['sha256','output_sha256']:
        for n,h in check[k].items():assert digest(n)==h
    source=cp/'pre-fixup.json';gold=json.loads(source.read_text());m=gold['modules']['top'];cells=m['cells'];names,late,cones,cuts=discover(cells)
    reference=Path(check['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()};sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'}
    free=[site+'/'+letter+'6LUT' for site in sites-bad for letter in 'ABCD' if site+'/'+letter+'5LUT' not in occupied and site+'/'+letter+'6LUT' not in occupied]
    def xy(s):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',s).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    bits={b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}|{b for v in m['netnames'].values() for b in v['bits'] if isinstance(b,int)};fresh=max(bits)+1;added={};nets={};replacements={};original={};placements={};targets=[]
    def reduce(ins,truth):
        support=[i for i in range(len(ins)) if any(truth[x]!=truth[x^(1<<i)] for x in range(len(truth)))];return [ins[i] for i in support],[truth[sum(((x>>j)&1)<<i for j,i in enumerate(support))] for x in range(1<<len(support))]
    final_bels={n:take(placed[n]["attributes"]["NEXTPNR_BEL"]) for n in names}
    for ti,n in enumerate(names):
        cone=cones[n];leaves=cuts[n];early=[b for b in leaves if b not in late];local=[];cache={};near=placed[n]['attributes']['NEXTPNR_BEL']
        def make(ins,truth):
            nonlocal fresh
            ins,truth=reduce(ins,truth);key=(tuple(ins),tuple(truth))
            if key in cache:return cache[key]
            if len(ins)>6:
                choices=[]
                for i in range(len(ins)):
                    rest=ins[:i]+ins[i+1:];ts=[[truth[(x&((1<<i)-1))|((x>>i)<<(i+1))|(v<<i)] for x in range(1<<len(rest))] for v in [0,1]];choices.append((sum(len(reduce(rest,t)[0]) for t in ts),i,rest,ts))
                _,i,rest,ts=min(choices,key=lambda z:(z[0],z[1]));b0=make(rest,ts[0]);b1=make(rest,ts[1]);return make([b0,b1,ins[i]],[(x>>((x>>2)&1))&1 for x in range(8)])
            if not ins:ins=[early[0]];truth=truth*2
            nn=f'$tiny3tpu$selector_cofactor_{ti}_{len(local)}';bit=fresh;fresh+=1;added[nn]=packed(ins,bit,sum(v<<i for i,v in enumerate(truth)));local.append(nn);nets[nn+'$net']=dict(hide_name=1,bits=[bit],attributes={});placements[nn]=take(near);cache[key]=bit;return bit
        patterns=[]
        for word in range(1<<len(early)):
            pattern=0
            for state in range(1<<len(late)):
                vs={b:(word>>i)&1 for i,b in enumerate(early)};vs.update({b:(state>>i)&1 for i,b in enumerate(late)})
                for c in cone.values():vs[logical(c)[1]['O']]=evaluate(c,vs)
                pattern|=vs[logical(cells[n])[1]['O']]<<state
            patterns.append(pattern)
        codes={0:0,51:1,85:2,240:4,243:5,245:6};assert set(patterns)<=set(codes)
        co=[make(early,[(codes[pat]>>i)&1 for pat in patterns]) for i in range(3)]
        inverse={code:pat for pat,code in codes.items()}
        finalmask=sum(((inverse.get(w&7,0)>>(w>>3))&1)<<w for w in range(64))
        old=cells[n];new=packed(co+late,logical(old)[1]['O'],finalmask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k!='X_ORIG_TYPE'});original[n]=old;replacements[n]=new;placements[n]=final_bels[n]
        assert 'CONSTR_PARENT' not in old['attributes']
        for child in old['attributes'].get('CONSTR_CHILDREN','').split(';'):
            if not child:continue
            assert cells[child]['type']=='SLICE_FFX' and cells[child]['attributes']['CONSTR_PARENT']==n;original[child]=cells[child];replacements[child]=copy.deepcopy(cells[child]);replacements[child]['attributes']={k:v for k,v in replacements[child]['attributes'].items() if not k.startswith('CONSTR_')}
        targets.append(dict(name=n,added=local,cuts=leaves))
    patch=dict(passed=True,kind='packed_selector_three_control_encoding',checkpoint=str(manifest),late_inputs=late,targets=targets,original_cells=original,replacements=replacements,added_cells=added,added_netnames=nets,placements=placements,added_latency_cycles=0);apply_verified(patch,gold);out.mkdir();oldcone={k:v for co in cones.values() for k,v in co.items()};newcone={**added,**{n:replacements[n] for n in names}};roots=[logical(cells[n])[1]['O'] for n in names];leaves=sorted(set(b for cut in cuts.values() for b in cut));text=emit(oldcone,leaves,roots,'gold')+'\n'+emit(newcone,leaves,roots,'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire [15:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n';(out/'miter.v').write_text(text)
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {out/"miter.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']={str(q.resolve()):digest(q) for q in [manifest,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),yosys,lib,out/'miter.v',script,out/'prove.log']};(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print(json.dumps(dict(passed=True,targets=len(names),added_luts=len(added),exhaustive_cases=sum(1<<len(v) for v in cuts.values()),primitive_sat=True,late_inputs_absent_from_all_cofactors=True)))
if __name__=='__main__':main()
