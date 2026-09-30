#!/usr/bin/env python3
"""Prove a single packed jump-decode LUT edit while preserving every other cell."""
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest

def verify_patch(patch,design):
    cells=design['modules']['top']['cells'];target=patch['target'];cone=patch['cone']
    assert all(cells[n]==c for n,c in cone.items()) and cells[target]==patch['original_cell']
    logical={}
    for n,c in cone.items():
        assert c['type']=='SLICE_LUTX' and c['attributes']['X_ORIG_TYPE'] in ['LUT2','LUT3']
        ports={c['attributes']['X_ORIG_PORT_'+p]:bs for p,bs in c['connections'].items()}
        width=int(c['attributes']['X_ORIG_TYPE'][3:]);assert set(ports)=={f'I{i}' for i in range(width)}|{'O'}
        assert all(len(bs)==1 and isinstance(bs[0],int) for bs in ports.values())
        logical[ports['O'][0]]=(width,ports,int(c['parameters']['INIT'],2))
    leaves=sorted({bs[0] for _,ports,_ in logical.values() for p,bs in ports.items() if p!='O'}-set(logical))
    assert len(leaves)==5 and leaves==patch['leaves']
    root=cells[target]['connections']['O6'][0]
    def ev(b,values):
        if b in values:return values[b]
        w,ports,mask=logical[b];idx=sum(ev(ports[f'I{i}'][0],values)<<i for i in range(w));return (mask>>idx)&1
    truth=[ev(root,{b:(v>>i)&1 for i,b in enumerate(leaves)}) for v in range(32)]
    expected=copy.deepcopy(cells[target]);expected['parameters']={'INIT':format(sum(v<<i for i,v in enumerate(truth)),'032b')}
    expected['attributes']={k:v for k,v in expected['attributes'].items() if not k.startswith('X_ORIG_PORT_')}
    expected['attributes'].update(X_ORIG_TYPE='LUT5',X_ORIG_PORT_O6='O')
    expected['attributes'].update({f'X_ORIG_PORT_A{i+1}':f'I{i}' for i in range(5)})
    expected['connections']={**{f'A{i+1}':[b] for i,b in enumerate(leaves)},'O6':[root]}
    expected['port_directions']={p:'output' if p=='O6' else 'input' for p in expected['connections']}
    assert expected==patch['replacement'] and truth==patch['truth_table']
    assert not any(k.startswith('CONSTR') for k in cells[target]['attributes'])
    return expected

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists()
    cp=a.checkpoint.resolve();manifest=json.loads((cp/'manifest.json').read_text());assert manifest['passed']
    for key in ['sha256','output_sha256']:
        for n,h in manifest[key].items():assert digest(n)==h,n
    source=cp/'pre-fixup.json';design=json.loads(source.read_text());cells=design['modules']['top']['cells']
    names=[next(n for n in cells if n.endswith('$'+str(i))) for i in [220954,220952,220998]];target=names[-1];cone={n:cells[n] for n in names}
    logical={c['connections']['O6'][0]:c for c in cone.values()};outputs=set(logical)
    leaves=sorted({b for c in cone.values() for p,bs in c['connections'].items() if p!='O6' for b in bs}-outputs)
    def ev(b,values):
        if b in values:return values[b]
        c=logical[b];con={c['attributes']['X_ORIG_PORT_'+p]:bs[0] for p,bs in c['connections'].items()};w=int(c['attributes']['X_ORIG_TYPE'][3:]);idx=sum(ev(con[f'I{i}'],values)<<i for i in range(w));return (int(c['parameters']['INIT'],2)>>idx)&1
    truth=[ev(cells[target]['connections']['O6'][0],{b:(v>>i)&1 for i,b in enumerate(leaves)}) for v in range(32)]
    new=copy.deepcopy(cells[target]);new['parameters']={'INIT':format(sum(v<<i for i,v in enumerate(truth)),'032b')}
    new['attributes']={k:v for k,v in new['attributes'].items() if not k.startswith('X_ORIG_PORT_')};new['attributes'].update(X_ORIG_TYPE='LUT5',X_ORIG_PORT_O6='O');new['attributes'].update({f'X_ORIG_PORT_A{i+1}':f'I{i}' for i in range(5)})
    new['connections']={**{f'A{i+1}':[b] for i,b in enumerate(leaves)},'O6':cells[target]['connections']['O6']};new['port_directions']={p:'output' if p=='O6' else 'input' for p in new['connections']}
    record=dict(passed=True,kind='packed_jump_decode_collapse',checkpoint=str(cp/'manifest.json'),target=target,cone=cone,original_cell=cells[target],replacement=new,leaves=leaves,truth_table=truth,added_latency_cycles=0,sha256={str(q):digest(q) for q in [cp/'manifest.json',source,Path(__file__).resolve()]})
    assert verify_patch(record,design)==new
    a.out.write_text(json.dumps(record,indent=2)+'\n');print('PASS packed LUT collapse, all 32 inputs, no state or latency changes')
if __name__=='__main__':main()
