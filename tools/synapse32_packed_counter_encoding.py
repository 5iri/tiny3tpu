#!/usr/bin/env python3
"""Factor late DDR controls out of packed occupancy-counter update cones."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_selector_dma_dual_guard_ready import apply_verified as apply_base
from synapse32_packed_selector_patch_v4 import logical as lut_logical,packed

def logical(c):
    if c['type']=='SLICE_LUTX':return lut_logical(c)
    assert c['type']=='SELMUX2_1' and c['attributes']['X_ORIG_TYPE'] in ['MUXF7','MUXF8']
    return 3,dict(I0=c['connections']['0'][0],I1=c['connections']['1'][0],I2=c['connections']['S0'][0],O=c['connections']['OUT'][0]),0xca

def evaluate(c,values):
    w,p,t=logical(c);return (t>>sum(values[p[f'I{i}']]<<i for i in range(w)))&1

def discover(m):
    cs=m['cells'];ls={n:logical(c) for n,c in cs.items() if (c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT')) or c['type']=='SELMUX2_1'};drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};g=next(n for n in ls if n.endswith('$217011'));ce=next(n for n in ls if n.endswith('$217100'));late=[ls[g][1]['I1'],ls[ce][1]['O']];memo={};active=set()
    def dep(b):
        if b in late:return True
        if b in memo:return memo[b]
        if b not in drv:return False
        n=drv[b];c=cs[n]
        if n not in ls and c['type']!='CARRY4':return False
        assert b not in active;active.add(b)
        ins=[ls[n][1][f'I{i}'] for i in range(ls[n][0])] if n in ls else [v for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for v in bs]
        v=any(dep(v) for v in ins);active.remove(b);memo[b]=v;return v
    targets=[];cones={};cuts={}
    for alias,v in sorted(m['netnames'].items()):
        if not alias.startswith(('memory.main_write_id_buffer_level[','memory.main_write_w_buffer_level2[')):continue
        assert len(v['bits'])==1;ff=next(n for n,c in cs.items() if c['type']=='SLICE_FFX' and c['connections'].get('Q')==v['bits']);b=cs[ff]['connections']['D'][0];root=drv[b];cone={};leaves=set()
        def walk(b):
            if b in late or not dep(b):leaves.add(b);return
            n=drv[b];assert n in ls, ('late-dependent unsupported primitive',n,cs[n]['type'])
            if n in cone:return
            w,p,_=ls[n]
            for i in range(w):walk(p[f'I{i}'])
            cone[n]=cs[n]
        walk(b);assert root in cone;targets.append(dict(name=root,ff=ff,alias=alias));cones[root]=cone;cuts[root]=sorted(leaves)
    assert len(targets)==10 and len({v['name'] for v in targets})==10
    return targets,late,cones,cuts

def emit(cells,leaves,roots,name):
    bits=sorted({v for c in cells.values() for v in logical(c)[1].values()});lines=[f'module {name}(input [{len(leaves)-1}:0] x,output [{len(roots)-1}:0] y);','wire '+','.join(f'n{b}' for b in bits)+';'];lines += [f'assign n{b}=x[{i}];' for i,b in enumerate(leaves)]+[f'assign y[{i}]=n{b};' for i,b in enumerate(roots)]
    for i,c in enumerate(cells.values()):
        w,p,t=logical(c)
        if c['type']=='SELMUX2_1':lines.append(f'{c["attributes"]["X_ORIG_TYPE"]} u{i}(.I0(n{p["I0"]}),.I1(n{p["I1"]}),.S(n{p["I2"]}),.O(n{p["O"]}));')
        else:lines.append(f'LUT{w} #(.INIT({1<<w}\'b{t:0{1<<w}b})) u{i}('+','.join(f'.{k}(n{v})' for k,v in p.items())+');')
    return '\n'.join(lines+['endmodule'])

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0
    base=apply_base(patch['base_patch'],design);m=base['modules']['top'];cs=m['cells'];targets,late,cones,cuts=discover(m);assert patch['counter_late_inputs']==late and [v['name'] for v in targets]==[v['name'] for v in patch['counter_targets']]
    for n,c in patch['base_patch']['replacements'].items():assert patch['replacements'][n]==c
    for field in ['added_cells','added_netnames']:
        for n,c in patch['base_patch'][field].items():assert patch[field][n]==c
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    extra=set(patch['added_cells'])-set(patch['base_patch']['added_cells']);assert extra=={n for item in patch['counter_targets'] for n in item['added']}
    oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']};newbits={logical(patch['added_cells'][n])[1]['O'] for n in extra};assert len(newbits)==len(extra) and not newbits&oldbits and not extra&set(cs)
    for item in patch['counter_targets']:
        n=item['name'];assert item['cuts']==cuts[n];available=set(cuts[n])-set(late)
        for an in item['added']:
            w,p,_=logical(patch['added_cells'][an]);assert {p[f'I{i}'] for i in range(w)}<=available;available.add(p['O'])
        root=patch['replacements'][n];assert logical(root)[1]['O']==logical(cs[n])[1]['O']
        for word in range(1<<len(cuts[n])):
            values={b:(word>>i)&1 for i,b in enumerate(cuts[n])};expected=values.copy()
            for c in cones[n].values():expected[logical(c)[1]['O']]=evaluate(c,expected)
            for an in item['added']:
                c=patch['added_cells'][an];values[logical(c)[1]['O']]=evaluate(c,values)
            assert evaluate(root,values)==expected[logical(cs[n])[1]['O']]
    roots={v['name'] for v in targets}
    for n in set(patch['replacements'])-set(patch['base_patch']['replacements'])-roots:
        a=copy.deepcopy(cs[n]);b=copy.deepcopy(patch['replacements'][n])
        for c in [a,b]:c['attributes']={k:v for k,v in c['attributes'].items() if not k.startswith('CONSTR_')}
        assert a==b
    actual=copy.deepcopy(base);am=actual['modules']['top'];am['cells'].update(copy.deepcopy(patch['replacements']));am['cells'].update(copy.deepcopy(patch['added_cells']));am['netnames'].update(copy.deepcopy(patch['added_netnames']));return actual

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();bp=a.base_patch.resolve();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];cs=m['cells'];targets,late,cones,cuts=discover(m);reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(prior['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_counter_encoding',base_patch=prior,counter_targets=[],counter_late_inputs=late);fresh=max(b for c in cs.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1
    final_bels={v['name']:take(placed[v['ff']]['attributes']['NEXTPNR_BEL']) for v in targets}
    def reduce(ins,t):
        support=[i for i in range(len(ins)) if any(t[x]!=t[x^(1<<i)] for x in range(len(t)))];return [ins[i] for i in support],[t[sum(((x>>j)&1)<<i for j,i in enumerate(support))] for x in range(1<<len(support))]
    for ti,item in enumerate(targets):
        n=item['name'];early=[b for b in cuts[n] if b not in late];local=[];cache={};near=placed[item['ff']]['attributes']['NEXTPNR_BEL']
        def make(ins,t):
            nonlocal fresh
            ins,t=reduce(ins,t);key=(tuple(ins),tuple(t))
            if key in cache:return cache[key]
            if len(ins)>6:
                choices=[]
                for i in range(len(ins)):
                    rest=ins[:i]+ins[i+1:];ts=[[t[(x&((1<<i)-1))|((x>>i)<<(i+1))|(v<<i)] for x in range(1<<len(rest))] for v in [0,1]];choices.append((sum(len(reduce(rest,q)[0]) for q in ts),i,rest,ts))
                _,i,rest,ts=min(choices,key=lambda x:(x[0],x[1]));b0=make(rest,ts[0]);b1=make(rest,ts[1]);b=make([b0,b1,ins[i]],[(x>>((x>>2)&1))&1 for x in range(8)]);cache[key]=b;return b
            if not ins:ins=[early[0]];t=t*2
            an=f'$tiny3tpu$counter_encoder_{ti}_{len(local)}';b=fresh;fresh+=1;patch['added_cells'][an]=packed(ins,b,sum(v<<i for i,v in enumerate(t)));patch['added_netnames'][an+'$net']=dict(hide_name=1,bits=[b],attributes={});patch['placements'][an]=take(near);local.append(an);cache[key]=b;return b
        patterns=[]
        for word in range(1<<len(early)):
            pat=0
            for state in range(4):
                values={b:(word>>i)&1 for i,b in enumerate(early)};values.update({b:(state>>i)&1 for i,b in enumerate(late)})
                for c in cones[n].values():values[logical(c)[1]['O']]=evaluate(c,values)
                pat|=values[logical(cs[n])[1]['O']]<<state
            patterns.append(pat)
        unique=sorted(set(patterns));codes={p:i for i,p in enumerate(unique)};width=max(1,(len(unique)-1).bit_length());assert width+2<=6;encoded=[make(early,[(codes[p]>>i)&1 for p in patterns]) for i in range(width)];mask=sum(((unique[w&((1<<width)-1)]>>(w>>width))&1)<<w for w in range(1<<(width+2)) if (w&((1<<width)-1))<len(unique));new=packed(encoded+late,logical(cs[n])[1]['O'],mask);old=cs[n];new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});patch['original_cells'][n]=gold['modules']['top']['cells'][n];patch['replacements'][n]=new;patch['placements'][n]=final_bels[n]
        assert 'CONSTR_PARENT' not in old['attributes'],n
        for child in old['attributes'].get('CONSTR_CHILDREN','').split(';'):
            if not child:continue
            assert cs[child]['attributes']['CONSTR_PARENT']==n
            patch['original_cells'][child]=gold['modules']['top']['cells'][child];patch['replacements'][child]=copy.deepcopy(cs[child]);patch['replacements'][child]['attributes']={k:v for k,v in cs[child]['attributes'].items() if not k.startswith('CONSTR_')}
        patch['counter_targets'].append(dict(**item,added=local,cuts=cuts[n],function_classes=len(unique),encoder_bits=width))
    apply_verified(patch,gold);out.mkdir();oldcone={n:c for co in cones.values() for n,c in co.items()};newcone={n:patch['added_cells'][n] for item in patch['counter_targets'] for n in item['added']};newcone.update({v['name']:patch['replacements'][v['name']] for v in targets});outs={logical(c)[1]['O'] for c in oldcone.values()};leaves=sorted({v for c in oldcone.values() for k,v in logical(c)[1].items() if k!='O'}-outs);roots=[logical(cs[v['name']])[1]['O'] for v in targets];(out/'miter.v').write_text(emit(oldcone,leaves,roots,'gold')+'\n'+emit(newcone,leaves,roots,'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire [9:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {out/"miter.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_selector_dma_dual_guard_ready.py'),yosys,lib,out/'miter.v',script,out/'prove.log']});patch['counter_cases']=sum(1<<len(v) for v in cuts.values());(out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print(json.dumps(dict(passed=True,counter_cases=patch['counter_cases'],counter_added_luts=sum(len(v['added']) for v in patch['counter_targets']),counter_primitive_sat=True,added_latency_cycles=0)))
if __name__=='__main__':main()
