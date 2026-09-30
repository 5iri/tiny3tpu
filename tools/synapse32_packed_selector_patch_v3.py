#!/usr/bin/env python3
"""Factor a packed DDR selector bus so late address comparisons cross one LUT."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest

def logical(c):
    assert c['type']=='SLICE_LUTX'
    width=int(c['attributes']['X_ORIG_TYPE'][3:]);ports={}
    for p,bs in c['connections'].items():
        roles=c['attributes'].get('X_ORIG_PORT_'+p,'').split()
        for role in roles:assert len(bs)==1;ports[role]=bs[0]
    assert set(ports)=={f'I{i}' for i in range(width)}|{'O'}
    return width,ports,int(c['parameters']['INIT'],2)

def evaluate(c,values):
    w,p,mask=logical(c);return (mask>>sum(values[p[f'I{i}']]<<i for i in range(w)))&1

def packed(inputs,out,mask):
    w=len(inputs);assert 1<=w<=6
    return dict(hide_name=1,type='SLICE_LUTX',parameters={'INIT':format(mask,f'0{1<<w}b')},attributes={'X_ORIG_TYPE':f'LUT{w}','X_ORIG_PORT_O6':'O',**{f'X_ORIG_PORT_A{i+1}':f'I{i}' for i in range(w)}},port_directions={**{f'A{i+1}':'input' for i in range(w)},'O6':'output'},connections={**{f'A{i+1}':[b] for i,b in enumerate(inputs)},'O6':[out]})

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0
    m=design['modules']['top'];cells=m['cells'];shared=patch['shared'];g=cells[shared];gw,gp,gm=logical(g)
    assert gw==5 and gm&65535==0 and g==patch['original_shared']
    targets=patch['targets'];assert len(targets)==16
    for n,old in patch['original_cells'].items():assert cells[n]==old
    assert not set(patch['added_cells'])&set(cells) and not set(patch['added_netnames'])&set(m['netnames'])
    outputs={logical(c)[1]['O'] for c in patch['added_cells'].values()}
    oldbits={b for c in cells.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']}
    assert len(outputs)==32 and not outputs&oldbits
    for item in targets:
        n=item['name'];old=cells[n];w,fp,fm=logical(old);assert w==5
        gindex=next(i for i in range(w) if fp[f'I{i}']==gp['O']);other=[fp[f'I{i}'] for i in range(w) if i!=gindex]
        leaves=sorted(set(other+[gp[f'I{i}'] for i in range(gw)]));assert len(leaves)==9
        added={k:patch['added_cells'][k] for k in item['added']};replacement=patch['replacements'][n]
        for word in range(512):
            values={b:(word>>i)&1 for i,b in enumerate(leaves)};expected=evaluate(old,{**values,gp['O']:evaluate(g,values)})
            for c in added.values():values[logical(c)[1]['O']]=evaluate(c,values)
            assert evaluate(replacement,values)==expected
        assert logical(replacement)[1]['O']==fp['O']
    changed=set(patch['replacements'])-set(v['name'] for v in targets)
    for n in changed:
        before=copy.deepcopy(cells[n]);after=copy.deepcopy(patch['replacements'][n]);assert before['type']=='SLICE_FFX'
        for c in [before,after]:c['attributes']={k:v for k,v in c['attributes'].items() if not k.startswith('CONSTR_')}
        assert before==after
    actual=copy.deepcopy(design);am=actual['modules']['top'];am['cells'].update(copy.deepcopy(patch['replacements']));am['cells'].update(copy.deepcopy(patch['added_cells']));am['netnames'].update(copy.deepcopy(patch['added_netnames']))
    return actual

def emit(cells,leaves,roots,name):
    bits=sorted({b for c in cells.values() for b in logical(c)[1].values()});lines=[f'module {name}(input [{len(leaves)-1}:0] x,output [{len(roots)-1}:0] y);','wire '+','.join(f'n{b}' for b in bits)+';']
    lines += [f'assign n{b}=x[{i}];' for i,b in enumerate(leaves)]+[f'assign y[{i}]=n{b};' for i,b in enumerate(roots)]
    for i,c in enumerate(cells.values()):
        w,p,mask=logical(c);ports=','.join(f'.{k}(n{v})' for k,v in p.items());lines.append(f'LUT{w} #(.INIT({1<<w}\'b{mask:0{1<<w}b})) u{i}({ports});')
    return '\n'.join(lines+['endmodule'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();cp=a.checkpoint.resolve();out=a.out.resolve();assert not out.exists()
    manifest=cp/'manifest.json';check=json.loads(manifest.read_text());assert check['passed'] and check['routed_json_exact']
    for k in ['sha256','output_sha256']:
        for n,h in check[k].items():assert digest(n)==h,n
    source=cp/'pre-fixup.json';gold=json.loads(source.read_text());m=gold['modules']['top'];cells=m['cells'];shared=next(n for n in cells if n.endswith('$217011'));g=cells[shared];gw,gp,gm=logical(g);assert gw==5 and gm&65535==0
    names=[n for n,c in cells.items() if c['type']=='SLICE_LUTX' and gp['O'] in [b for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for b in bs]];assert len(names)==16
    oldbits={b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}|{b for v in m['netnames'].values() for b in v['bits'] if isinstance(b,int)}|{b for v in m['ports'].values() for b in v['bits'] if isinstance(b,int)};fresh=max(oldbits)+1
    original={};replacements={};added={};nets={};targets=[];placements={}
    reference=Path(check['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells']
    occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()};sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type']=='CARRY4' or c['attributes'].get('X_ORIG_TYPE')=='RAMD32' or c['type']=='SELMUX2_1'}
    free=[site+'/'+letter for site in sites-bad for letter in 'ABCD' if site+'/'+letter+'5LUT' not in occupied and site+'/'+letter+'6LUT' not in occupied]
    def xy(s):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',s).groups()))
    def take(near,need_outmux=False):
        x,y=xy(near);available=[v for v in free if not need_outmux or v+'5FF' not in occupied];assert available
        v=min(available,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    for i,n in enumerate(sorted(names)):
        old=cells[n];w,fp,fm=logical(old);assert w==5
        gi=next(j for j in range(5) if fp[f'I{j}']==gp['O']);other=[fp[f'I{j}'] for j in range(5) if j!=gi]
        def outer(word,gv):
            vs={b:(word>>j)&1 for j,b in enumerate(other)};vs[gp['O']]=gv;return evaluate(old,vs)
        base=sum(outer(word,0)<<word for word in range(16));delta=sum(((outer(word&15,0)^outer(word&15,1))&((word>>4)&1))<<word for word in range(32))
        bn=f'$tiny3tpu$selector_base_{i}';dn=f'$tiny3tpu$selector_delta_{i}';added[bn]=packed(other,fresh,base);added[dn]=packed(other+[gp['I4']],fresh+1,delta)
        finalmask=sum((((word&1)^(((word>>1)&1)&((gm>>16>>(word>>2))&1))))<<word for word in range(64))
        new=packed([fresh,fresh+1]+[gp[f'I{j}'] for j in range(4)],fp['O'],finalmask)
        new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith(('X_ORIG_PORT_','CONSTR_')) and k!='X_ORIG_TYPE'})
        original[n]=old;replacements[n]=new
        assert 'CONSTR_PARENT' not in old['attributes']
        for child in old['attributes'].get('CONSTR_CHILDREN','').split(';'):
            if not child:continue
            assert cells[child]['type']=='SLICE_FFX' and cells[child]['attributes']['CONSTR_PARENT']==n
            original[child]=cells[child];replacements[child]=copy.deepcopy(cells[child]);replacements[child]['attributes']={k:v for k,v in replacements[child]['attributes'].items() if not k.startswith('CONSTR_')}
        near=placed[n]['attributes']['NEXTPNR_BEL'];finalsite=take(near);pairsite=take(near,need_outmux=True);placements[n]=finalsite+'6LUT';placements[bn]=pairsite+'6LUT';placements[dn]=pairsite+'5LUT'
        for suffix,bit in [('base',fresh),('delta',fresh+1)]:nets[f'$tiny3tpu$selector_{suffix}_net_{i}']=dict(hide_name=1,bits=[bit],attributes={})
        targets.append(dict(name=n,added=[bn,dn]));fresh+=2
    patch=dict(passed=True,kind='packed_selector_late_compare',checkpoint=str(manifest),shared=shared,original_shared=g,targets=targets,original_cells=original,replacements=replacements,added_cells=added,added_netnames=nets,placements=placements,added_latency_cycles=0)
    actual=apply_verified(patch,gold)
    out.mkdir();roots=[logical(cells[v['name']])[1]['O'] for v in targets];oldcone={shared:g,**{n:cells[n] for n in names}};newcone={**added,**{n:replacements[n] for n in names}};outputs=set(roots+[gp['O']]);leaves=sorted({b for c in oldcone.values() for p,b in logical(c)[1].items() if p!='O'}-outputs)
    text=emit(oldcone,leaves,roots,'gold')+'\n'+emit(newcone,leaves,roots,'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire [15:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n';(out/'miter.v').write_text(text)
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {out/"miter.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']={str(q):digest(q) for q in [manifest,source,reference,Path(__file__).resolve(),yosys,lib,out/'miter.v',script,out/'prove.log']}
    (out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print(json.dumps(dict(passed=True,targets=16,added_luts=32,exhaustive_cases=8192,primitive_sat=True,added_latency_cycles=0)))
if __name__=='__main__':main()
