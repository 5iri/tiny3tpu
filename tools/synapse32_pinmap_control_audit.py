#!/usr/bin/env python3
"""Check packed logical ports, expanding shared-pin labels and retaining every state/IO cell."""
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_equivalence import canonical_cells

def functional_cells(design):
    result=canonical_cells(design);supplemental=[]
    for mn,mod in result.items():
        for n,c in mod.items():
            if c['type']!='SLICE_LUTX':continue
            kind=c['attributes']['X_ORIG_TYPE'];assert kind=='RAMD32' or re.fullmatch('LUT[1-6]',kind),kind
            con={};directions={}
            for pin,bits in c['connections'].items():
                if re.fullmatch('A[1-6]',pin):
                    assert c['port_directions'][pin]=='input'
                    supplemental.append(dict(cell=n,pin=pin,nets=bits))
                    if kind=='RAMD32' and pin=='A6':assert bits==[(('$PACKER_VCC_NET',0),)]
                    continue
                for role in pin.split():
                    if role in con:assert con[role]==bits and directions[role]==c['port_directions'][pin]
                    con[role]=bits;directions[role]=c['port_directions'][pin]
            expected={f'I{i}' for i in range(int(kind[3:]))} if kind!='RAMD32' else {f'{prefix}{i}' for prefix in ['RADR','WADR'] for i in range(5)}|{'CLK','WE'}
            assert expected<=set(con),(n,kind,sorted(expected-set(con)))
            c['connections']=con;c['port_directions']=directions
    return result,supplemental

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['checkpoint','disabled','enabled','out']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();assert not a.out.exists();seen=set();records=[];hashes={}
    def check(path):
        path=path.resolve();d=json.loads(path.read_text());hashes[str(path)]=digest(path)
        if path in seen:return d
        seen.add(path)
        for k in ['sha256','output_sha256','baseline_sha256']:
            for n,h in d.get(k,{}).items():assert digest(n)==h,(path,n)
        records.append(dict(path=str(path),sha256=digest(path)))
        return d
    cp=check(a.checkpoint/'manifest.json');disabled=check(a.disabled/'manifest.json');enabled=check(a.enabled/'manifest.json')
    assert cp['passed'] and disabled['passed'] and enabled['passed']
    assert not disabled['enabled'] and disabled['routed_json_exact'] and disabled['timing_graph_exact']
    assert enabled['enabled'] and enabled['only_logical_labels_changed'] and enabled['native_fmax_exact']
    assert disabled['parent']==enabled['parent']
    fixed=check(Path(enabled['parent']));assert fixed['checkpoint']==str((a.checkpoint/'manifest.json').resolve())
    reference=a.checkpoint/'pre-fixup.json';routed=a.enabled/'routed.json'
    gold=json.loads(reference.read_text());actual=json.loads(routed.read_text())
    before,extra_before=functional_cells(gold);after,extra_after=functional_cells(actual)
    assert before==after,'Every logical cell, parameter, port, net alias and non-placement attribute must agree'
    old=json.loads((Path(cp['parent']).parent/'routed.json').read_text())
    assert {n:c['attributes']['NEXTPNR_BEL'] for n,c in old['modules']['top']['cells'].items()}=={n:c['attributes']['NEXTPNR_BEL'] for n,c in actual['modules']['top']['cells'].items()}
    for q in [reference,routed,Path(__file__).resolve(),Path(__file__).with_name('synapse32_packed_equivalence.py').resolve()]:hashes[str(q.resolve())]=digest(q)
    result=dict(passed=True,logical_cells_exact=True,all_logical_inputs_present=True,placement_exact=True,restored_labels=enabled['restored_labels'],supplemental_input_pins_before=len(extra_before),supplemental_input_pins_after=len(extra_after),scope='Expand every shared logical pin label. Compare every cell, state/IO port, parameter, logical input/output and net alias. Only unmapped shared physical A1..A6 pins are excluded from the functional comparison; every original LUT input and RAM read/write address remains mandatory. RAM A6 ties are checked. This does not validate physical routing, skew, hold or DDR IO timing.',full_soc_timing_accepted=False,checked_manifests=records,sha256=hashes)
    a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(passed=True,logical_cells_exact=True,restored_labels=len(enabled['restored_labels']),full_soc_timing_accepted=False)))

if __name__=='__main__':main()
