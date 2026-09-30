"""Replicate one DDR data selector near two receiver groups, without changing state."""
import argparse, copy, gc, json, re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_mid_zero_flag import apply_verified as apply_base
from synapse32_packed_counter_encoding import logical, evaluate
from synapse32_packed_selector_patch_v4 import packed
from synapse32_recovered_hashes_v2 import RecoveredHashes
gc.disable()
FIELDS = ['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']
SOURCE = '$abc$216920$auto$blifparse.cc:557:parse_blif$229056'

def xy(bel):
    return tuple(map(int, re.search(r'SLICE_X(\d+)Y(\d+)', bel).groups()))

def expected(base, groups):
    m=base['modules']['top']; cs=m['cells']; c=cs[SOURCE]; width, ports, table=logical(c)
    assert width==3 and c['attributes']['X_ORIG_TYPE']=='LUT3'
    sinks={n for n,v in cs.items() if v['type']=='SLICE_FFX' and v['connections']['D']==[ports['O']]}
    consumers={(n,p) for n,v in cs.items() for p,bs in v['connections'].items() if v['port_directions'][p]=='input' and ports['O'] in bs}
    assert consumers=={(n,'D') for n in sinks} and len(sinks)==16
    bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']}
    fresh=max(b for b in bits if isinstance(b,int))+1
    assert len(groups)==2 and all(groups) and not set(groups[0])&set(groups[1])
    assert set(sum(groups,[]))<sinks
    adds={}; replacements={}; nets={}
    for i,group in enumerate(groups):
        assert group==sorted(set(group))
        name=f'$tiny3tpu$wdata_229056_geographic_{i}'
        adds[name]=packed([ports[f'I{j}'] for j in range(width)],fresh+i,table)
        nets[name+'$net']=dict(hide_name=1,bits=[fresh+i],attributes={})
        for n in group:
            f=copy.deepcopy(cs[n]); assert f['attributes']['X_ORIG_TYPE'] in ['FDRE','FDSE']
            f['connections']['D']=[fresh+i]; replacements[n]=f
        for word in range(8):
            values={ports[f'I{j}']:(word>>j)&1 for j in range(width)}
            assert evaluate(c,values)==evaluate(adds[name],values)
    return adds,replacements,nets

def apply_verified(patch, design):
    assert patch['passed'] and patch['added_latency_cycles']==0
    bp=Path(patch['geographic_base']); assert digest(bp)==patch['geographic_base_sha256']
    prior=json.loads(bp.read_text()); base=apply_base(prior,design)
    adds,replacements,nets=expected(base,patch['geographic_groups'])
    for k,extra in [('added_cells',adds),('replacements',replacements),('added_netnames',nets)]:
        assert not set(prior[k])&set(extra); assert patch[k]=={**prior[k],**extra}
    for k in ['checkpoint','original_cells','removed_cells','removed_netnames','added_latency_cycles']:
        assert patch[k]==prior[k]
    assert set(patch['placements'])==set(prior['placements'])|set(adds)
    assert all(patch['placements'][n]==b for n,b in prior['placements'].items())
    assert all(patch['placements'][n].endswith('6LUT') for n in adds)
    base['modules']['top']['cells'].update(copy.deepcopy(adds))
    base['modules']['top']['cells'].update(copy.deepcopy(replacements))
    base['modules']['top']['netnames'].update(copy.deepcopy(nets))
    return base

def main():
    p=argparse.ArgumentParser()
    for k in ['base-patch','reference','out','recovery']:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--legacy-recovery',type=Path,nargs=2,required=True)
    a=p.parse_args(); out=a.out.resolve(); assert not out.exists()
    recovery=RecoveredHashes(a.recovery,a.legacy_recovery)
    bp=a.base_patch.resolve(); prior=json.loads(bp.read_text()); rp=a.reference.resolve()/'manifest.json'; record=json.loads(rp.read_text())
    assert prior['passed'] and record['passed'] and Path(record['patch'])==bp
    for d in [prior,record]:
        for k in ['sha256','output_sha256']:
            for n,h in d.get(k,{}).items(): recovery.check(n,h)
    source=Path(prior['checkpoint']).parent/'pre-fixup.json'; gold=json.loads(source.read_text()); base=apply_base(prior,gold)
    ref=a.reference.resolve()/'routed.json'; placed=json.loads(ref.read_text())['modules']['top']['cells']; cs=base['modules']['top']['cells']; port=logical(cs[SOURCE])[1]['O']
    sinks=[n for n,c in cs.items() if c['type']=='SLICE_FFX' and c['connections']['D']==[port]]
    groups=[sorted(n for n in sinks if xy(placed[n]['attributes']['NEXTPNR_BEL'])[1]<60),sorted(n for n in sinks if 60<=xy(placed[n]['attributes']['NEXTPNR_BEL'])[1]<110)]
    adds,replacements,nets=expected(base,groups)
    patch={k:copy.deepcopy(prior[k]) for k in FIELDS}
    patch.update(kind='packed_wdata_geographic_replicas',geographic_base=str(bp),geographic_base_sha256=digest(bp),geographic_groups=groups)
    for k,extra in [('added_cells',adds),('replacements',replacements),('added_netnames',nets)]:patch[k].update(extra)
    occupied={c['attributes']['NEXTPNR_BEL'] for c in placed.values()}; sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')}
    bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL'))}
    free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if all(s+'/'+l+t not in occupied for t in ['5LUT','6LUT'])]
    evidence=[]
    for name,group in zip(adds,groups):
        points=[xy(placed[n]['attributes']['NEXTPNR_BEL']) for n in group]
        def cost(b):
            x,y=xy(b); return (max(abs(x-u)+abs(y-v) for u,v in points),sum(abs(x-u)+abs(y-v) for u,v in points),b)
        bel=min(free,key=cost); free.remove(bel); patch['placements'][name]=bel
        evidence.append(dict(name=name,bel=bel,receivers=len(group),maximum_distance=cost(bel)[0]))
    apply_verified(patch,gold)
    negatives=[]
    # Reject an actual LUT truth-table mutation and changes to FF timing/control ports.
    for label in ['lut','clock','reset','enable','init']:
        badpatch=copy.deepcopy(patch)
        if label=='lut':
            name=next(iter(adds)); w,ps,t=logical(adds[name]);badpatch['added_cells'][name]=packed([ps[f'I{i}'] for i in range(w)],ps['O'],t^1)
        else:
            n=groups[0][0]
            if label=='init':badpatch['replacements'][n]['parameters']['INIT']='1' if replacements[n]['parameters']['INIT']=='0' else '0'
            else:badpatch['replacements'][n]['connections'][dict(clock='CK',reset='SR',enable='CE')[label]]=[] if replacements[n]['connections'][dict(clock='CK',reset='SR',enable='CE')[label]] else [999999999]
        try: apply_verified(badpatch,gold)
        except AssertionError: negatives.append(label)
        else: raise AssertionError('Corruption was accepted: '+label)
    patch['proof']=dict(actual_primitive_exhaustive_cases=8,replicas=2,changed_register_d_inputs=sum(map(len,groups)),state_cells_added=0,all_other_register_fields_exact=True,negative_controls_rejected=negatives)
    patch['placement_evidence']=evidence
    patch['sha256']={n:recovery.check(n,h) for n,h in prior['sha256'].items()}
    patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_mid_zero_flag.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),a.recovery,*a.legacy_recovery]})
    out.mkdir();(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n')
    print(json.dumps(dict(passed=True,proof=patch['proof'],placements=evidence)))
if __name__=='__main__':main()
