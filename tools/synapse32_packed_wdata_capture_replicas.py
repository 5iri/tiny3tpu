"""Clone two data-select LUTs locally; retain the original capture registers."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_branch_carry_cuts_v2 import apply_verified as apply_base
from synapse32_packed_counter_encoding import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed


def pairs(cs):
    return [dict(source=next(n for n in cs if n.endswith('$'+s)),ff=next(n for n in cs if n.endswith('$'+f)),name='$tiny3tpu$wdata_capture_replica_'+f) for s,f in [('229060','68660'),('229059','68661')]]


def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0;prior=patch['wdata_replica_base'];base=apply_base(prior,design);cs=base['modules']['top']['cells'];ps=pairs(cs);assert ps==patch['wdata_replica_pairs']
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in prior[field].items():assert patch[field][n]==c
    names={p['name'] for p in ps};targets={p['ff'] for p in ps};assert set(patch['replacements'])==set(prior['replacements'])|targets;assert set(patch['added_cells'])==set(prior['added_cells'])|names;assert set(patch['added_netnames'])==set(prior['added_netnames'])|{n+'$net' for n in names}
    oldbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in base['modules']['top']['netnames'].values() for b in v['bits']}|{b for v in base['modules']['top']['ports'].values() for b in v['bits']};fresh=set()
    for item in ps:
        source,ff,name=item['source'],item['ff'],item['name'];w,p,t=logical(cs[source]);cw,cp,ct=logical(patch['added_cells'][name]);assert w==cw==3 and t==ct and all(p[f'I{i}']==cp[f'I{i}'] for i in range(w));assert cp['O'] not in oldbits|fresh;fresh.add(cp['O']);assert cs[ff]['type']=='SLICE_FFX' and cs[ff]['connections']['D']==[p['O']] and not any(k.startswith('CONSTR_') for k in cs[ff]['attributes'])
        expected=copy.deepcopy(cs[ff]);expected['connections']['D']=[cp['O']];assert patch['replacements'][ff]==expected;assert patch['added_netnames'][name+'$net']['bits']==[cp['O']]
        for word in range(8):
            values={p[f'I{i}']:(word>>i)&1 for i in range(w)};assert evaluate(cs[source],values)==evaluate(patch['added_cells'][name],values)
    m=base['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return base


def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();bp=a.base_patch.resolve();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source_path=cp.parent/'pre-fixup.json';gold=json.loads(source_path.read_text());base=apply_base(prior,gold);cs=base['modules']['top']['cells'];ps=pairs(cs);patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_wdata_capture_replicas',wdata_replica_base=prior,wdata_replica_pairs=ps)
    allbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in base['modules']['top']['netnames'].values() for b in v['bits']}|{b for v in base['modules']['top']['ports'].values() for b in v['bits']};fresh=max(b for b in allbits if isinstance(b,int))+1
    for item in ps:
        source,ff,name=item['source'],item['ff'],item['name'];w,p,t=logical(cs[source]);assert w==3;patch['added_cells'][name]=packed([p[f'I{i}'] for i in range(w)],fresh,t);patch['added_netnames'][name+'$net']=dict(hide_name=1,bits=[fresh],attributes={});new=copy.deepcopy(cs[ff]);assert new['connections']['D']==[p['O']];new['connections']['D']=[fresh];fresh+=1;patch['replacements'][ff]=new;patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in [source,ff]})
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(patch['placements'].values());sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
    for item in ps:
        x,y=xy(placed[item['ff']]['attributes']['NEXTPNR_BEL']);bel=min(free,key=lambda b:(abs(xy(b)[0]-x)+abs(xy(b)[1]-y),b));free.remove(bel);patch['placements'][item['name']]=bel
    apply_verified(patch,gold);old={p['source']:cs[p['source']] for p in ps};new={p['name']:patch['added_cells'][p['name']] for p in ps};leaves=sorted({v for c in old.values() for k,v in logical(c)[1].items() if k!='O'});assert len(leaves)<=6;oldouts=[logical(old[p['source']])[1]['O'] for p in ps];newouts=[logical(new[p['name']])[1]['O'] for p in ps]
    for word in range(1<<len(leaves)):
        values={b:(word>>i)&1 for i,b in enumerate(leaves)};assert [evaluate(c,values) for c in old.values()]==[evaluate(c,values) for c in new.values()]
    out.mkdir();mv=out/'miter.v';mv.write_text(emit(old,leaves,oldouts,'gold')+'\n'+emit(new,leaves,newouts,'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire [1:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n');yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {mv}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source_path,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_branch_carry_cuts_v2.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),mv,ys,out/'prove.log',yosys,lib]});patch['capture_proof']=dict(cases=1<<len(leaves),ff_clock_enable_reset_q_parameters_exact=True,only_d_rewired_to_equivalent_logic=True,added_registers=0,added_latency_cycles=0);(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,**patch['capture_proof'],actual_primitive_sat=True,added_luts=2)))
if __name__=='__main__':main()
