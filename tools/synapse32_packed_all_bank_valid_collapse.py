#!/usr/bin/env python3
"""Prove bounded LUT collapses from observed critical paths, using a hashed parent reference."""
import gc
gc.disable()  # JSON/netlist trees are acyclic; retain normal reference counting.
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_ddr_ready_macro_encoding_v2 import apply_verified as apply_base,logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed

FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles']
def replacement(cs,inner,root):
    for n in [inner,root]:
        c=cs[n];assert c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT')
        if n==inner:assert not any(k.startswith('CONSTR_') for k in c['attributes'])
        else:
            assert n.split('$')[-1] in {'223157': '79267', '223126': '79370', '223061': '79473', '223052': '77999', '223135': '77893', '223092': '77679', '223110': '77566'} and 'CONSTR_PARENT' not in c['attributes']
            children=list(filter(None,c['attributes'].get('CONSTR_CHILDREN','').split(';')));assert len(children)==1
            child=children[0];assert child.endswith('$'+{'223157': '79267', '223126': '79370', '223061': '79473', '223052': '77999', '223135': '77893', '223092': '77679', '223110': '77566'}[n.split('$')[-1]]) and cs[child]['type']=='SLICE_FFX' and cs[child]['attributes']['CONSTR_PARENT']==n
    ip=logical(cs[inner])[1];rp=logical(cs[root])[1];ri={v for k,v in rp.items() if k!='O'}
    assert ip['O'] in ri
    cuts=sorted((ri|{v for k,v in ip.items() if k!='O'})-{ip['O']})
    assert rp['O'] not in cuts and all(isinstance(b,int) for b in cuts)
    if len(cuts)>6:return None
    mask=0
    for word in range(1<<len(cuts)):
        vs={b:(word>>i)&1 for i,b in enumerate(cuts)}
        mask|=evaluate(cs[root],{**vs,ip['O']:evaluate(cs[inner],vs)})<<word
    old=cs[root];new=packed(cuts,rp['O'],mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']})
    return new,cuts

def parent(patch):
    p=Path(patch['collapse_base_path']);assert p.is_absolute() and digest(p)==patch['collapse_base_sha256']
    prior=json.loads(p.read_text());assert prior['passed'];return prior

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0;prior=parent(patch);base=apply_base(prior,design);cs=base['modules']['top']['cells']
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['added_cells','added_netnames']:assert patch[field]==prior[field]
    assert patch['checkpoint']==prior['checkpoint'];roots=[]
    for step in patch['collapse_steps']:
        inner,root=step['inner'],step['root'];assert root not in prior['replacements'] and root not in roots
        result=replacement(cs,inner,root);assert result is not None;new,cuts=result
        assert cuts==step['cuts'] and new==patch['replacements'][root]
        for word in range(1<<len(cuts)):
            vs={b:(word>>i)&1 for i,b in enumerate(cuts)}
            assert evaluate(new,vs)==evaluate(cs[root],{**vs,logical(cs[inner])[1]['O']:evaluate(cs[inner],vs)})
        cs[root]=copy.deepcopy(new);roots.append(root)
    assert roots and set(patch['replacements'])==set(prior['replacements'])|set(roots)
    for n,c in prior['replacements'].items():assert patch['replacements'][n]==c
    return base

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--candidates',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists()
    prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    candidates=json.loads(a.candidates.read_text())
    for n,h in candidates['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);cs=base['modules']['top']['cells'];original=copy.deepcopy(cs)
    patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_critical_lut_collapse',collapse_base_path=str(bp),collapse_base_sha256=digest(bp),collapse_steps=[])
    skipped=[];roots=set();nodes=set()
    for c in candidates['candidates']:
        inner,root=c['inner'],c['root']
        if root in prior['replacements'] or root in roots:skipped.append(dict(root=root,reason='already replaced'));continue
        result=replacement(cs,inner,root)
        if result is None:skipped.append(dict(root=root,reason='composed cone exceeds six inputs'));continue
        new,cuts=result;patch['collapse_steps'].append(dict(inner=inner,root=root,cuts=cuts));patch['replacements'][root]=new;patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [inner,root]});cs[root]=copy.deepcopy(new);roots.add(root);nodes.update([inner,root])
    assert roots
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'}
    free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    for root in sorted(roots):
        bel=placed[root]['attributes']['NEXTPNR_BEL'];assert bel.endswith('6LUT')
        sibling=bel.removesuffix('6LUT')+'5LUT';assert sibling not in occupied
        assert not any(v==bel for n,v in patch['placements'].items() if n!=root)
        patch['placements'][root]=bel
    apply_verified(patch,gold)
    oldcone={n:original[n] for n in sorted(nodes)};newcone={n:cs[n] for n in sorted(nodes)};outputs={logical(c)[1]['O'] for c in oldcone.values()};cuts=sorted({v for c in oldcone.values() for k,v in logical(c)[1].items() if k!='O'}-outputs);outs=[logical(original[n])[1]['O'] for n in sorted(roots)]
    assert {v for c in newcone.values() for k,v in logical(c)[1].items() if k!='O'}<=set(cuts)|outputs
    out.mkdir();miter=out/'miter.v';miter.write_text(emit(oldcone,cuts,outs,'gold')+'\n'+emit(newcone,cuts,outs,'candidate')+f'\nmodule proof(input [{len(cuts)-1}:0] x,output same);wire [{len(outs)-1}:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {miter}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch.update(skipped=skipped,joint_outputs=len(outs),joint_cut_count=len(cuts),exhaustive_cases=sum(1<<len(s['cuts']) for s in patch['collapse_steps']))
    patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,a.candidates,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_ddr_ready_macro_encoding_v2.py'),yosys,lib,miter,script,out/'prove.log']})
    (out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,joint_outputs=len(outs),cases=patch['exhaustive_cases'],primitive_sat=True,added_latency_cycles=0)))
if __name__=='__main__':main()
