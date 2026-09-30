#!/usr/bin/env python3
"""Trace each selected register setup endpoint separately, preserving global timing maxima."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from synapse32_analyze_timing_endpoints import analyze


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sensitivity',type=Path,required=True)
    p.add_argument('--pattern',required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();assert not a.out.exists()
    folder=a.sensitivity.resolve();manifest=folder/'manifest.json'
    m=json.loads(manifest.read_text())
    for n,h in m['sha256'].items():assert digest(n)==h,n
    v=next(v for v in m['variants'] if v['symbolic_pcout_ns']==0 and v['symbolic_carry_arc_ns']==.1)
    graph=folder/'graph-pcout-0-carry-0.1.tsv';assert digest(graph)==v['graph_sha256']
    names={};cells=set();pattern=re.compile(a.pattern)
    for line in graph.open():
        r=line.rstrip('\n').split('\t')
        if r[0]=='PORT':
            names[r[1],r[3]]=r[-1]
            if r[3]=='Q' and pattern.search(r[-1]):cells.add(r[1])
    assert cells,a.pattern
    result=analyze(graph,tracked_cells=cells,track_each_endpoint=True)
    assert result['maxima']==v['maxima'], 'Endpoint tracking changed global timing maxima';assert not result['unresolved_nodes']
    paths=[r for r in result['tracked_maxima'] if r['group']=='tracked_input']
    assert paths
    for r in paths:
        for point in r['path']:point['net']=names[point['cell'],point['port']]
        r['state_net']=names[r['cell'],'Q']
    paths.sort(key=lambda r:-r['arrival_ns'])
    report=dict(pattern=a.pattern,cells=sorted(cells),paths=paths,
        scope='Expanded model with symbolic carry=0.1 ns and PCOUT=0; not physical timing signoff.',
        full_soc_timing_accepted=False,sha256={str(p):digest(p) for p in [manifest,graph,Path(__file__).resolve(),Path(__file__).with_name('synapse32_analyze_timing_endpoints.py').resolve()]})
    a.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(worst_ns=paths[0]['arrival_ns'],state_net=paths[0]['state_net'],path=paths[0]['path'])))


if __name__=='__main__':main()
