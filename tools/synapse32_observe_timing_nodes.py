#!/usr/bin/env python3
"""Expose combinational node arrivals without changing the timing graph or endpoint budgets."""
import argparse,json,re
from pathlib import Path
from synapse32_analyze_timing_graph_nodes import analyze
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--sensitivity',type=Path,required=True);p.add_argument('--pattern',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();manifest=a.sensitivity/'manifest.json';m=json.loads(manifest.read_text())
for n,h in m['sha256'].items():assert digest(n)==h,n
v=next(v for v in m['variants'] if v['symbolic_pcout_ns']==0 and v['symbolic_carry_arc_ns']==.1);graph=a.sensitivity/'graph-pcout-0-carry-0.1.tsv';assert digest(graph)==v['graph_sha256'];pat=re.compile(a.pattern);cells=set()
for line in graph.open():
 r=line.rstrip('\n').split('\t')
 if r[0]=='PORT' and pat.search(r[1]):cells.add(r[1])
assert cells;result=analyze(graph,tracked_cells=cells);assert not result['unresolved_nodes']
def scores(rows):return {(r['source_clock'],r['source_edge'],r['sink_clock'],r['sink_edge']):r['arrival_ns'] for r in rows}
assert scores(result['maxima'])==scores(v['maxima'])
old=Path(__file__).with_name('synapse32_analyze_timing_graph.py');new=Path(__file__).with_name('synapse32_analyze_timing_graph_nodes.py');added="                observed_nodes=[dict(cell=k[0],port=k[1],net=ports[k][1],port_class=ports[k][0],source_clock=d[0],source_edge=d[1],arrival_ns=v[0]/1000,path=trace(k,d)) for k,ds in arrival.items() if k[0] in tracked_cells for d,v in ds.items()],\n";assert new.read_text().replace(added,'')==old.read_text()
rows=sorted(result['observed_nodes'],key=lambda r:-r['arrival_ns']);assert rows;a.out.write_text(json.dumps(dict(passed=True,pattern=a.pattern,observed_nodes=rows,endpoint_domain_maxima_unchanged=True,scope='Arrival at internal nodes, without endpoint setup. Same expanded diagnostic graph and evaluator; no physical timing acceptance.',full_soc_timing_accepted=False,sha256={str(p.resolve()):digest(p) for p in [manifest,graph,old,new,Path(__file__)]}),indent=2)+'\n');print('PASS node observation; endpoint domain maxima unchanged')
