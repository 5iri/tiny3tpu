"""Share early cofactors across all four DMA write-strobe outputs."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_bank5_valid_collapse import apply_verified as apply_base,logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
from synapse32_lut_bdd_equivalence import compare as bdd_compare


def discover(m):
    cs=m['cells'];ls={n:logical(c) for n,c in cs.items() if c['type']=='SELMUX2_1' or c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT')}
    drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
    roots=[next(n for n in ls if n.endswith('$'+s)) for s in ['217426','217436','217437','223961']];late=53544;memo={};active=set()
    def dep(b):
        if b==late:return True
        if b in memo:return memo[b]
        n=drv[b];c=cs[n]
        if n not in ls and c['type']!='CARRY4':
            assert c['type'] in ['SLICE_FFX','PSEUDO_GND','PSEUDO_VCC','GND','VCC'],(n,c['type']);return False
        assert b not in active;active.add(b)
        ins=[ls[n][1][f'I{i}'] for i in range(ls[n][0])] if n in ls else [v for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for v in bs]
        value=any(dep(v) for v in ins);active.remove(b);memo[b]=value;return value
    cone={};cuts=set()
    def walk(b):
        if b==late or not dep(b):cuts.add(b);return
        n=drv[b];assert n in ls,('unsupported late-dependent primitive',n)
        if n in cone:return
        w,p,_=ls[n]
        for i in range(w):walk(p[f'I{i}'])
        cone[n]=cs[n]
    for root in roots:walk(ls[root][1]['O'])
    assert len(cone)==6 and len(cuts)<=16 and all(root in cone for root in roots)
    return roots,late,cone,sorted(cuts)


def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0
    prior=patch['wstrb_vector_base'];base=apply_base(prior,design);cs=base['modules']['top']['cells'];roots,late,cone,cuts=discover(base['modules']['top'])
    assert patch['wstrb_vector_roots']==roots and patch['wstrb_vector_late']==late and patch['wstrb_vector_cuts']==cuts and patch['wstrb_vector_cone']==list(cone)
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in prior[field].items():assert patch[field][n]==c
    assert set(patch['replacements'])==set(prior['replacements'])|set(roots)
    names=patch['wstrb_vector_early'];assert len(names)==len(set(names));assert set(patch['added_cells'])==set(prior['added_cells'])|set(names)
    assert set(patch['added_netnames'])==set(prior['added_netnames'])|{n+'$net' for n in names}
    oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for n in base['modules']['top']['netnames'].values() for b in n['bits']};available=set(cuts)-{late}
    for n in names:
        w,p,_=logical(patch['added_cells'][n]);assert {p[f'I{i}'] for i in range(w)}<=available and p['O'] not in oldbits|available;available.add(p['O'])
    for root in roots:
        w,p,_=logical(patch['replacements'][root]);assert p['O']==logical(cs[root])[1]['O'] and {p[f'I{i}'] for i in range(w)}<=available|{late}
        assert not any(k.startswith('CONSTR_') for k in cs[root]['attributes'])
    new={n:patch['added_cells'][n] for n in names};new.update({r:patch['replacements'][r] for r in roots})
    bdd_compare(cone,new,cuts,[logical(cs[r])[1]['O'] for r in roots])
    m=base['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return base


def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();prior=json.loads(a.base_patch.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);cs=base['modules']['top']['cells'];roots,late,cone,cuts=discover(base['modules']['top'])
    patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_wstrb_vector_choice',wstrb_vector_base=prior,wstrb_vector_roots=roots,wstrb_vector_late=late,wstrb_vector_cuts=cuts,wstrb_vector_cone=list(cone),wstrb_vector_early=[])
    fresh=max(b for c in cs.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1;cache={};co=[]
    for state in [0,1]:
        sub={late:('constant',state)}
        for n,c in cone.items():
            w,p,_=logical(c);mapped={p[f'I{i}']:sub.get(p[f'I{i}'],p[f'I{i}']) for i in range(w)};ins=list(dict.fromkeys(v for v in mapped.values() if isinstance(v,int)));truth=[]
            for word in range(1<<len(ins)):
                vs={b:(word>>i)&1 for i,b in enumerate(ins)};truth.append(evaluate(c,{b:(v[1] if isinstance(v,tuple) else vs[v]) for b,v in mapped.items()}))
            support=[i for i in range(len(ins)) if any(truth[x]!=truth[x^(1<<i)] for x in range(len(truth)))];values=[truth[sum(((x>>j)&1)<<i for j,i in enumerate(support))] for x in range(1<<len(support))];ins=[ins[i] for i in support];mask=sum(v<<i for i,v in enumerate(values));ob=p['O']
            if not ins:sub[ob]=('constant',mask);continue
            if len(ins)==1 and mask==2:sub[ob]=ins[0];continue
            key=(tuple(ins),mask)
            if key not in cache:
                name=f'$tiny3tpu$wstrb_vector_early_{len(patch["wstrb_vector_early"])}';bit=fresh;fresh+=1;patch['added_cells'][name]=packed(ins,bit,mask);patch['added_netnames'][name+'$net']=dict(hide_name=1,bits=[bit],attributes={});patch['wstrb_vector_early'].append(name);cache[key]=bit
            sub[ob]=cache[key]
        co.append({r:sub[logical(cs[r])[1]['O']] for r in roots})
    finals={}
    for root in roots:
        pair=[c[root] for c in co];ins=list(dict.fromkeys([v for v in pair if isinstance(v,int)]+[late]));mask=0
        for word in range(1<<len(ins)):
            vals={b:(word>>i)&1 for i,b in enumerate(ins)};value=pair[vals[late]];mask|=(value[1] if isinstance(value,tuple) else vals[value])<<word
        old=cs[root];assert not any(k.startswith('CONSTR_') for k in old['attributes']);new=packed(ins,logical(old)[1]['O'],mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']});patch['replacements'][root]=new;finals[root]=ins
    byout={logical(patch['added_cells'][n])[1]['O']:n for n in patch['wstrb_vector_early']};needed=set()
    def need(b):
        if b not in byout:return
        n=byout[b]
        if n in needed:return
        needed.add(n);w,p,_=logical(patch['added_cells'][n])
        for i in range(w):need(p[f'I{i}'])
    for ins in finals.values():
        for b in ins:need(b)
    for n in patch['wstrb_vector_early'][:]:
        if n not in needed:del patch['added_cells'][n];del patch['added_netnames'][n+'$net'];patch['wstrb_vector_early'].remove(n)
    patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in cone})
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    for root in roots:patch['placements'][root]=take(placed[root]['attributes']['NEXTPNR_BEL'])
    for n in patch['wstrb_vector_early']:patch['placements'][n]=take(placed[roots[0]]['attributes']['NEXTPNR_BEL'])
    apply_verified(patch,gold);out.mkdir();new={n:patch['added_cells'][n] for n in patch['wstrb_vector_early']};new.update({r:patch['replacements'][r] for r in roots});outs=[logical(cs[r])[1]['O'] for r in roots];mv=out/'miter.v';mv.write_text(emit(cone,cuts,outs,'gold')+'\n'+emit(new,cuts,outs,'candidate')+f'\nmodule proof(input [{len(cuts)-1}:0] x,output same);wire [3:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n');yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {mv}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [a.base_patch,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_bank5_valid_collapse.py'),Path(__file__).with_name('synapse32_lut_bdd_equivalence.py'),mv,ys,out/'prove.log',yosys,lib]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,outputs=4,cuts=len(cuts),early_luts=len(patch['wstrb_vector_early']),canonical_bdd_equivalence=True,actual_primitive_sat=True,added_latency_cycles=0)))
if __name__=='__main__':main()
