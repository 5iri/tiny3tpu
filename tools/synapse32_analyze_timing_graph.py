#!/usr/bin/env python3
"""Independent maximum-delay graph analysis; reproduces exported model only.

Supports output nodes with both clock-to-output and combinational origins.
This does not add missing primitive models or establish physical signoff.
"""
import argparse
from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path


# This Xilinx backend stores delay_t as integer picoseconds; getDelayNS
# exports float nanoseconds. Recover the original integer before summation.
def ps(value):
    return round(float(value)*1000)


def analyze(path, tracked_cells=()):
    tracked_cells=set(tracked_cells)
    ports, clocks, raw_edges = {}, defaultdict(list), []
    with path.open() as f:
        assert next(f).rstrip() == 'VERSION\t1'
        for line in f:
            v=line.rstrip('\n').split('\t')
            if v[0]=='PORT':
                _,c,t,p,d,cls,n,net=v
                ports[c,p]=(int(cls),net)
            elif v[0]=='CLOCK':
                _,c,p,i,cp,e,s,h,q=v
                clocks[c,p].append((cp,int(e),ps(s),ps(q)))
            elif v[0]=='CELLARC':
                _,c,p,o,d=v; raw_edges.append(((c,p),(c,o),ps(d)))
            elif v[0]=='NETARC':
                _,n,c,p,s,k,d=v; raw_edges.append(((c,p),(s,k),ps(d)))
    # Exclude ignored/clock-only ports, exactly as this exported model does.
    active={k for k,v in ports.items() if v[0] not in (0,1,8)}
    edges=defaultdict(list); indegree={k:0 for k in active}
    for u,v,d in raw_edges:
        if u in active and v in active:
            edges[u].append((v,d)); indegree[v]+=1
    arrival=defaultdict(dict)
    for k,checks in clocks.items():
        if k not in active: continue
        if ports[k][0] not in (3,5): continue
        for cp,e,s,q in checks:
            # Keep tracked origins separate: a faster tracked path must not
            # disappear when an unrelated launch in the same clock wins.
            domain=(ports[k[0],cp][1],e,k[0] in tracked_cells)
            arrival[k][domain]=(q,None)
    queue=deque(k for k,n in indegree.items() if n==0)
    visited=0
    while queue:
        u=queue.popleft();visited+=1
        for v,d in edges[u]:
            for domain,(a,_) in arrival[u].items():
                if domain not in arrival[v] or a+d>arrival[v][domain][0]:
                    arrival[v][domain]=(a+d,u)
            indegree[v]-=1
            if indegree[v]==0:queue.append(v)
    loops=sorted(k for k,n in indegree.items() if n)
    endpoints=[]; maxima={}; tracked_maxima={}
    def trace(k, domain):
        path=[]
        while k is not None:
            a, previous = arrival[k][domain]
            path.append(dict(cell=k[0],port=k[1],arrival_ns=a/1000))
            k=previous
        return list(reversed(path))
    for k,checks in clocks.items():
        if ports[k][0]!=2:continue
        for cp,e,s,q in checks:
            dest=(ports[k[0],cp][1],e)
            for source,(a,_) in arrival[k].items():
                row=dict(cell=k[0],port=k[1],source_clock=source[0],source_edge=source[1],
                         sink_clock=dest[0],sink_edge=dest[1],arrival_ns=(a+s)/1000)
                if tracked_cells:
                    path=trace(k,source)
                    for group, applies in [('tracked_input',k[0] in tracked_cells),
                                           ('tracked_output',path[0]['cell'] in tracked_cells)]:
                        if applies:
                            tracked_key=(group,)+source[:2]+dest
                            if tracked_key not in tracked_maxima or row['arrival_ns']>tracked_maxima[tracked_key]['arrival_ns']:
                                tracked_maxima[tracked_key]=dict(row,group=group,path=path)
                pair=source[:2]+dest
                if pair not in maxima or row['arrival_ns']>maxima[pair]['arrival_ns']:maxima[pair]=row
                if a+s>=9000:endpoints.append(row)
    return dict(scope='Independent evaluation of exported model, including its omissions. No hold/skew/recovery-removal analysis.',
                nodes=len(active),visited=visited,unresolved_nodes=loops,
                tracked_maxima=list(tracked_maxima.values()),
                maxima=sorted(maxima.values(),key=lambda r:(r['source_clock'],r['sink_clock'],r['source_edge'],r['sink_edge'])),
                endpoints=sorted(endpoints,key=lambda r:(r['cell'],r['port'],r['source_clock'],r['source_edge'],r['sink_clock'],r['sink_edge'])),
                full_soc_timing_accepted=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',type=Path,required=True)
    p.add_argument('--reference-endpoints',type=Path,required=True);a=p.parse_args()
    root=a.replay.resolve();manifest=json.loads((root/'manifest.json').read_text())
    graph=root/'timing-graph.tsv'
    assert manifest['passed'] and hashlib.sha256(graph.read_bytes()).hexdigest()==manifest['graph_sha256']
    result=analyze(graph)
    def key(r):return tuple(r[k] for k in ('cell','port','source_clock','source_edge','sink_clock','sink_edge'))
    ref={key(r):r['arrival_ns'] for r in json.loads(a.reference_endpoints.read_text())}
    actual={key(r):r['arrival_ns'] for r in result['endpoints']}
    result['reference_endpoints']=str(a.reference_endpoints.resolve())
    result['endpoint_keys_equal']=actual.keys()==ref.keys()
    result['maximum_endpoint_error_ns']=max((abs(actual[k]-ref[k]) for k in actual.keys()&ref.keys()),default=None)
    result['baseline_reproduced']=result['endpoint_keys_equal'] and result['maximum_endpoint_error_ns'] is not None and result['maximum_endpoint_error_ns']<1e-5 and not result['unresolved_nodes']
    result['sha256']={str(q.resolve()):hashlib.sha256(q.read_bytes()).hexdigest() for q in [graph,a.reference_endpoints,Path(__file__)]}
    (root/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('endpoints','sha256','unresolved_nodes')},indent=2))
    if not result['baseline_reproduced']:raise SystemExit('Independent graph analysis does not reproduce baseline')


if __name__=='__main__':main()
