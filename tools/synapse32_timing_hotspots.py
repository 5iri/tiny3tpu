#!/usr/bin/env python3
"""List failing system/CPU setup endpoints in a hash-checked expanded timing graph."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from synapse32_analyze_timing_graph import analyze


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sensitivity',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();folder=a.sensitivity.resolve();assert not a.out.exists()
    manifest=folder/'manifest.json';m=json.loads(manifest.read_text())
    for name,h in m['sha256'].items():assert digest(name)==h,name
    v=next(v for v in m['variants'] if v['symbolic_pcout_ns']==0 and v['symbolic_carry_arc_ns']==.1)
    graph=folder/'graph-pcout-0-carry-0.1.tsv';assert digest(graph)==v['graph_sha256']
    result=analyze(graph);assert not result['unresolved_nodes']
    assert result['maxima']==v['maxima']
    ports={};state={}
    for line in graph.open():
        s=line.rstrip('\n').split('\t')
        if s[0]=='PORT':
            ports[s[1],s[3]]=s[-1]
            if s[3]=='Q':state[s[1]]=s[-1]
    failing=[];groups={}
    for e in result['endpoints']:
        if e['source_clock'] not in ('clk','soc.cpu_clk') or e['sink_clock'] not in ('clk','soc.cpu_clk'):continue
        if e['source_edge']!=0 or e['sink_edge']!=0:raise AssertionError('Unexpected system edge')
        if e['arrival_ns']<=10:continue
        row=dict(e,state_net=state.get(e['cell']),endpoint_net=ports[e['cell'],e['port']],budget_ns=10)
        name=row['state_net'] or row['endpoint_net']
        group=re.sub(r'\[\d+\]','',name)
        group=re.sub(r'(bitslip|bankmachine|phaseinjector|nativeportconverter)\d+',r'\1*',group)
        row['group']=group;failing.append(row)
        g=groups.setdefault(group,dict(group=group,endpoint_domain_pairs=0,worst_ns=0))
        g['endpoint_domain_pairs']+=1;g['worst_ns']=max(g['worst_ns'],e['arrival_ns'])
    failing.sort(key=lambda r:-r['arrival_ns'])
    groups=sorted(groups.values(),key=lambda r:-r['worst_ns'])
    output=dict(scope='Expanded-model setup endpoints only, for 10 ns related system/CPU domains. Counts are endpoint/domain pairs, not enumerated combinational paths. Missing/unvalidated physical, IO, hold and reset timing remain outside this diagnostic.',
        failing_endpoint_domain_pairs=len(failing),groups=groups,endpoints=failing,
        full_soc_timing_accepted=False,
        sha256={str(p):digest(p) for p in [manifest,graph,Path(__file__).resolve(),Path(__file__).with_name('synapse32_analyze_timing_graph.py').resolve()]})
    a.out.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(dict(failing_endpoint_domain_pairs=len(failing),top_groups=groups[:12])))


if __name__=='__main__':main()
