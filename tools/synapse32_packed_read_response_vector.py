#!/usr/bin/env python3
"""Compose eight independently proved read-response encoders and prove all outputs jointly."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_packed_read_response_encoded_branch import SELECTORS,apply_verified as apply_branch,logical,emit
from synapse32_packed_counter_encoding import apply_verified as apply_base
from synapse32_apply_bram_timing import digest
FIELDS=['original_cells','replacements','added_cells','added_netnames']
def merge(components):
    result={k:{} for k in FIELDS}
    for p in components:
        for k in FIELDS:
            for n,c in p[k].items():
                if n in result[k]:assert result[k][n]==c,(k,n)
                result[k][n]=copy.deepcopy(c)
    return result

def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0
    parts=patch['components'];assert [p['selector_id'] for p in parts]==sorted(SELECTORS)
    base=parts[0]['base_patch'];assert all(p['base_patch']==base for p in parts)
    for p in parts:apply_branch(p,design)
    combined=merge(parts)
    for k in FIELDS:assert patch[k]==combined[k],k
    extra=[n for p in parts for n in p['read_response_early_cells']];assert len(extra)==len(set(extra))==16
    bits=[logical(patch['added_cells'][n])[1]['O'] for n in extra];assert len(set(bits))==16
    roots={logical(p['replacements'][p['read_response_root']])[1]['O'] for p in parts};cuts={b for p in parts for b in p['read_response_cuts']};assert not roots&cuts and not set(bits)&cuts
    result=copy.deepcopy(design);m=result['modules']['top'];m['cells'].update(copy.deepcopy(combined['replacements']));m['cells'].update(copy.deepcopy(combined['added_cells']));m['netnames'].update(copy.deepcopy(combined['added_netnames']));return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--components',type=Path,nargs=8,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists()
    paths=[p.resolve() for p in a.components];parts=[json.loads(p.read_text()) for p in paths];assert [p['selector_id'] for p in parts]==sorted(SELECTORS)
    for part in parts:
        for n,h in part['sha256'].items():assert digest(n)==h,n
    base=parts[0]['base_patch'];cp=Path(base['checkpoint']);source=cp.parent/'pre-fixup.json';design=json.loads(source.read_text());patch=copy.deepcopy(base);patch.update(merge(parts));patch.update(kind='packed_read_response_vector',components=parts)
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}|set(base['placements'].values());sites={v.split('/')[0] for v in occupied if v.startswith('SLICE_')};bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(v):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',v).groups()))
    def take(near):
        x,y=xy(near);v=min(free,key=lambda v:(abs(xy(v)[0]-x)+abs(xy(v)[1]-y),v));free.remove(v);return v
    patch['placements']=copy.deepcopy(base['placements'])
    for part in parts:
        root=part['read_response_root'];near=placed[root]['attributes']['NEXTPNR_BEL'];patch['placements'][root]=take(near)
        for n in part['read_response_early_cells']:patch['placements'][n]=take(near)
    apply_verified(patch,design);out.mkdir();old={};new={};cuts=set();roots=[]
    for part in parts:
        for n in part['read_response_cone']:old[n]=design['modules']['top']['cells'][n]
        root=part['read_response_root'];new[root]=part['replacements'][root]
        for n in part['read_response_early_cells']:new[n]=part['added_cells'][n]
        cuts.update(part['read_response_cuts']);roots.append(logical(new[root])[1]['O'])
    cuts=sorted(cuts);miter=out/'miter.v';miter.write_text(emit(old,cuts,roots,'gold')+'\n'+emit(new,cuts,roots,'candidate')+f'\nmodule proof(input [{len(cuts)-1}:0] x,output same);wire [7:0] a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';script=out/'prove.ys';script.write_text(f'read_verilog {lib} {miter}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n')
    with (out/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'prove.log').read_text();patch['sha256']={}
    for part in parts:patch['sha256'].update(part['sha256'])
    patch['sha256'].update({str(p.resolve()):digest(p) for p in paths+[Path(__file__),source,reference,yosys,lib,miter,script,out/'prove.log',Path(__file__).with_name('synapse32_packed_read_response_encoded_branch.py')]});patch['joint_primitive_sat']=True;patch['joint_cut_count']=len(cuts);patch['exhaustive_branch_cases']=8192
    (out/'patch.json').write_text(json.dumps(patch,indent=2)+'\n');print(json.dumps(dict(passed=True,branches=8,added_encoder_luts=16,joint_cut_count=len(cuts),exhaustive_branch_cases=8192,joint_primitive_sat=True,added_latency_cycles=0)))
if __name__=='__main__':main()
