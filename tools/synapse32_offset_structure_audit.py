#!/usr/bin/env python3
"""Check whether synthesis put upper carry chains after the low-offset carry."""
import argparse,hashlib,json
from pathlib import Path
from collections import defaultdict,deque


def inspect(path):
    m=json.loads(path.read_text())['modules']['kc705_synapse32_top'];cells=m['cells'];names=m['netnames']
    forward=defaultdict(set);reverse=defaultdict(set);edge_cells=defaultdict(set)
    for n,c in cells.items():
        t=c['type']
        if not (t.startswith('LUT') or t in ['MUXF7','MUXF8','MUXF9','CARRY4','INV']):continue
        inputs={b for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for b in bs if isinstance(b,int)}
        outputs={b for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs if isinstance(b,int)}
        for u in inputs:
            for v in outputs:forward[u].add(v);reverse[v].add(u);edge_cells[u,v].add(n)
    def walk(start,edges):
        seen=set(start);queue=deque(start)
        while queue:
            for v in edges[queue.popleft()]:
                if v not in seen:seen.add(v);queue.append(v)
        return seen
    result={}
    for kind,channel in [('read','ar'),('write','aw')]:
        stem='memory.main_'+kind
        origin=names[stem+'_offset_low']['bits'][13]
        targets=[v for v in names[stem+'_'+channel+'_payload_addr']['bits'][13:] if isinstance(v,int)]
        a=walk([origin],forward);b=walk(targets,reverse)
        cone={n for (u,v),ns in edge_cells.items() if u in a and v in b for n in ns}
        carry=sorted(n for n in cone if cells[n]['type']=='CARRY4')
        kept={}
        for suffix in ['_offset_upper_inc','_offset_upper_dec']:
            net=names.get(stem+suffix)
            if net:
                kept[suffix]=dict(attributes=net['attributes'],late_carry_dependency=any(x in a for x in net['bits']))
        result[kind]=dict(late_carry_bit=origin,target_bits=len(targets),downstream_upper_carry_cells=carry,parallel_alternatives=kept)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists()
    parent=inspect(a.parent);candidate=inspect(a.candidate)
    passed=all(not v['downstream_upper_carry_cells'] and len(v['parallel_alternatives'])==2 and all(not r['late_carry_dependency'] for r in v['parallel_alternatives'].values()) for v in candidate.values())
    paths=[a.parent.resolve(),a.candidate.resolve(),Path(__file__).resolve()]
    record=dict(passed=passed,parent=parent,candidate=candidate,
        scope='Conservative LUT/mux/carry connectivity between the late low-part carry and the high address outputs. Checks a synthesis structure, not physical timing or correctness. Separate arithmetic proofs cover functional equality.',full_soc_timing_accepted=False,
        sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
    a.out.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,parent_carry_counts={k:len(v['downstream_upper_carry_cells']) for k,v in parent.items()},candidate_carry_counts={k:len(v['downstream_upper_carry_cells']) for k,v in candidate.items()})))
    raise SystemExit(0 if passed else 2)

if __name__=='__main__':main()
