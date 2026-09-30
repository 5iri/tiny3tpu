"""Replace instruction-only packed carry/decode cones with exact LUT6s."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_bank5_valid_collapse import apply_verified as apply_base,logical
from synapse32_packed_selector_patch_v4 import packed
from synapse32_factor_branch_predicate import evaluate,drivers_of,verilog,lut


def abstract(m):
    cs=m['cells'];constants={b:('1' if c['type']=='PSEUDO_VCC' else '0') for c in cs.values() if c['type'] in ['PSEUDO_GND','PSEUDO_VCC'] for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};out={};fresh=max(b for c in cs.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1
    for n,c in cs.items():
        if c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE','').startswith('LUT'):
            w,p,t=logical(c);out[n]=lut([constants.get(p[f'I{i}'],p[f'I{i}']) for i in range(w)],p['O'],t)
        elif c['type']=='CARRY4':
            con=c['connections'];params=c['parameters']
            # Unmodeled unconnected inputs fail closed if this cell is needed.
            if any(len(con.get(f'{p}{i}',[]))!=1 for p in ['S','DI'] for i in range(4)):continue
            # Unconnected primitive outputs get private proof-only wire names.
            outputs={}
            for p in ['O','CO']:
                outputs[p]=[]
                for i in range(4):
                    bs=con.get(f'{p}{i}',[]);assert len(bs)<=1
                    if bs:outputs[p].append(bs[0])
                    else:outputs[p].append(fresh);fresh+=1
            def pin(p):assert len(con.get(p,[]))==1,(n,p);return constants.get(con[p][0],con[p][0])
            if 'PRECYINIT_CONST' in params:
                initial=str(int(params['PRECYINIT_CONST'],2));assert initial in ['0','1'];ci='0';cy=initial
            elif con.get('CIN'):ci=pin('CIN');cy='0'
            elif con.get('CYINIT'):ci='0';cy=pin('CYINIT')
            else:ci='0';cy='0'
            ports={'CI':[ci],'CYINIT':[cy],'DI':[pin(f'DI{i}') for i in range(4)],'S':[pin(f'S{i}') for i in range(4)],'O':outputs['O'],'CO':outputs['CO']}
            out[n]=dict(type='CARRY4',parameters={},connections=ports,port_directions={p:('output' if p in ['O','CO'] else 'input') for p in ports})
    return out


def derive(m):
    cs=m['cells'];ids=[m['netnames'][f'soc.cpu.id_ex_inst0_instr_id_out[{i}]']['bits'][0] for i in range(7)];conditions=[m['netnames']['soc.cpu.ex_unit_inst0.'+n]['bits'][0] for n in ['branch_equal','branch_less_signed','branch_less_unsigned']];leaves=ids+conditions;assert len(set(leaves))==10
    cells=abstract(m);drivers=drivers_of(cells);changes=[]
    for suffix,expected in [('220970',[1,2,3,4,5,6]),('220971',[0,1,2,7,8,9])]:
        name=next(n for n in cs if n.endswith('$'+suffix));old=cs[name];assert old['type']=='SLICE_LUTX' and not any(k.startswith('CONSTR_') for k in old['attributes']);root=logical(old)[1]['O'];seen=set();truth=[]
        for word in range(1024):truth.append(evaluate(root,{b:(word>>i)&1 for i,b in enumerate(leaves)},drivers,seen))
        support=[i for i in range(10) if any(truth[w]!=truth[w^(1<<i)] for w in range(1024))];assert support==expected
        mask=sum(truth[sum(((w>>i)&1)<<j for i,j in enumerate(support))]<<w for w in range(64));inputs=[leaves[i] for i in support];new=packed(inputs,root,mask);new['hide_name']=old['hide_name'];new['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']})
        # Bind all primitive inputs, including unobserved upper carry stages.
        while True:
            previous=set(seen)
            for cn in previous:
                for p,bs in cells[cn]['connections'].items():
                    if cells[cn]['port_directions'][p]=='input':
                        for b in bs:evaluate(b,{v:0 for v in leaves},drivers,seen)
            if previous==seen:break
        changes.append(dict(name=name,root=root,support=support,inputs=inputs,mask=mask,replacement=new,truth=truth,cone={n:cells[n] for n in sorted(seen)}))
    return leaves,changes


def parent(patch):
    p=Path(patch['branch_carry_base_path']);assert digest(p)==patch['branch_carry_base_sha256'];return json.loads(p.read_text())


def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0;prior=parent(patch);base=apply_base(prior,design);leaves,changes=derive(base['modules']['top']);assert leaves==patch['branch_carry_leaves']
    assert [{k:v for k,v in c.items() if k not in ['replacement','cone','truth']} for c in changes]==patch['branch_carry_changes']
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for f in ['added_cells','added_netnames']:assert patch[f]==prior[f]
    roots={c['name'] for c in changes};assert not roots&set(prior['replacements']);assert set(patch['replacements'])==set(prior['replacements'])|roots
    for n,c in prior['replacements'].items():assert patch['replacements'][n]==c
    for c in changes:assert patch['replacements'][c['name']]==c['replacement'];base['modules']['top']['cells'][c['name']]=copy.deepcopy(c['replacement'])
    return base


def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();bp=a.base_patch.resolve();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);leaves,changes=derive(base['modules']['top']);fields=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles'];patch={k:copy.deepcopy(prior[k]) for k in fields};patch.update(kind='packed_branch_carry_cuts',branch_carry_base_path=str(bp),branch_carry_base_sha256=digest(bp),branch_carry_leaves=leaves,branch_carry_changes=[{k:v for k,v in c.items() if k not in ['replacement','cone','truth']} for c in changes])
    for c in changes:
        patch['replacements'][c['name']]=c['replacement'];patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in c['cone']})
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
    for c in changes:
        x,y=xy(placed[c['name']]['attributes']['NEXTPNR_BEL']);bel=min(free,key=lambda b:(abs(xy(b)[0]-x)+abs(xy(b)[1]-y),b));free.remove(bel);patch['placements'][c['name']]=bel
    apply_verified(patch,gold);out.mkdir();yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';proofs=[]
    for i,c in enumerate(changes):
        v=out/f'miter-{i}.v';v.write_text(verilog(c['cone'],leaves,c['root'],'gold')+'\n'+verilog({c['name']:lut(c['inputs'],c['root'],c['mask'])},leaves,c['root'],'candidate')+'\nmodule proof(input [9:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n');ys=out/f'prove-{i}.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/f'prove-{i}.log'
        with log.open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
        assert 'SUCCESS!' in log.read_text();proofs.extend([v,ys,log])
    patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_bank5_valid_collapse.py'),Path(__file__).with_name('synapse32_factor_branch_predicate.py'),yosys,lib,*proofs]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,cases=2048,actual_primitive_sat=True,replacements=2,added_latency_cycles=0)))
if __name__=='__main__':main()
