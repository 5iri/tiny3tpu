#!/usr/bin/env python3
"""Collapse one named LUT/MUX cone with six independent inputs, preserving all state."""
import argparse, copy, hashlib, json
from pathlib import Path

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(); parent=a.parent.resolve(); out=a.out.resolve()
    assert not out.exists()
    source=parent/'board/soc.json'; gold=json.loads(source.read_text())
    cells=gold['modules']['kc705_synapse32_top']['cells']
    names=[next(n for n,c in cells.items() if c['connections'].get('O')==[bit]) for bit in [12325,12326,12327]]
    assert all(n.startswith('$abc$216920$auto$blifparse.cc:557:parse_blif$223668.') for n in names)
    target=names[-1]; cone={n:cells[n] for n in names}
    assert [c['type'] for c in cone.values()]==['LUT4','LUT4','MUXF7']
    drivers={c['connections']['O'][0]:c for c in cone.values()}
    leaves=sorted({b for c in cone.values() for port,bs in c['connections'].items() if port!='O' for b in bs}-drivers.keys())
    assert len(leaves)==6 and all(isinstance(b,int) for b in leaves)
    def evaluate(bit,values):
        if bit in values: return values[bit]
        c=drivers[bit]; conn=c['connections']
        if c['type']=='MUXF7':
            return evaluate(conn['I'+str(evaluate(conn['S'][0],values))][0],values)
        idx=sum(evaluate(conn[f'I{i}'][0],values)<<i for i in range(int(c['type'][3:])))
        return (int(c['parameters']['INIT'],2)>>idx)&1
    root=cells[target]['connections']['O'][0]
    truth=[evaluate(root,{b:(w>>i)&1 for i,b in enumerate(leaves)}) for w in range(64)]
    new=copy.deepcopy(cells[target]); new['type']='LUT6'
    new['parameters']={'INIT':format(sum(v<<i for i,v in enumerate(truth)),'064b')}
    new['connections']={**{f'I{i}':[b] for i,b in enumerate(leaves)},'O':[root]}
    new['port_directions']={p:'output' if p=='O' else 'input' for p in new['connections']}
    actual=copy.deepcopy(gold);actual['modules']['kc705_synapse32_top']['cells'][target]=new
    restored=copy.deepcopy(actual);restored['modules']['kc705_synapse32_top']['cells'][target]=cells[target]
    assert restored==gold
    out.mkdir(); proof=out/'predicate-proof';proof.mkdir()
    record=dict(passed=True,claim='Exhaustive actual LUT4/LUT4/MUXF7 cone truth table over six arbitrary inputs; same output and no state or latency change.',cone=cone,leaves=leaves,truth_table=truth,replacement=new,added_latency_cycles=0,sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]})
    (proof/'results.json').write_text(json.dumps(record,indent=2)+'\n')
    board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
    for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
    record=dict(passed=True,kind='collapsed_sequencer_mux_lut',parent=str(parent),source=str(source),proof=str(proof/'results.json'),target=target,original_cell=cells[target],candidate_cell=new,added_latency_cycles=0,all_other_netlist_content_exact=True,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'iteration-integrity.json',parent/'mapping.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()})
    (out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n')
    print('PASS 64 independent input combinations; sequencer mux cone replaced with LUT6')

if __name__=='__main__':main()
