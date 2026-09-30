"""Trace all over-budget CPU/system endpoints in an incremental timing probe."""
import argparse,json
from pathlib import Path
from synapse32_analyze_timing_endpoints import analyze
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);a=p.parse_args();r=a.route.resolve();t=Path(str(r)+'-timing');graph=t/'graph-pcout-0-carry-0.1.tsv';mp=t/'manifest.json';m=json.loads(mp.read_text());variant=next(v for v in m['variants'] if v['symbolic_pcout_ns']==0 and v['symbolic_carry_arc_ns']==.1);assert digest(graph)==variant['graph_sha256'];src=t/'analysis-pcout-0-carry-0.1.json';base=json.loads(src.read_text());bad=[v for v in base['endpoints'] if v['arrival_ns']>10 and v['source_clock'] in ['clk','soc.cpu_clk'] and v['sink_clock'] in ['clk','soc.cpu_clk']];result=analyze(graph,tracked_cells={v['cell'] for v in bad},track_each_endpoint=True);assert result['maxima']==variant['maxima'] and not result['unresolved_nodes'];names={}
for line in graph.open():
 v=line.rstrip('\n').split('\t')
 if v[0]=='PORT':names[v[1],v[3]]=v[-1]
paths=[v for v in result['tracked_maxima'] if v['group']=='tracked_input' and v['arrival_ns']>10]
for v in paths:
 v['state_net']=names.get((v['cell'],'Q'))
 for pt in v['path']:pt['net']=names.get((pt['cell'],pt['port']))
paths.sort(key=lambda v:-v['arrival_ns']);out=r/'all-failing-paths.json';assert not out.exists();out.write_text(json.dumps(dict(paths=paths,full_soc_timing_accepted=False,sha256={str(p):digest(p) for p in [mp,graph,src,Path(__file__).resolve()]}),indent=2)+'\n');print('traced',len(paths),'failing endpoint/domain pairs')
