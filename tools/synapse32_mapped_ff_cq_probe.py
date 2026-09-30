"""Apply DS182 output CQ by placed FF type, retaining all other graph rows."""
import argparse,hashlib,json,re
from collections import Counter
from pathlib import Path
from synapse32_analyze_timing_endpoints import analyze
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--route',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();root=Path(__file__).resolve().parents[1];route=a.route.resolve();graph=Path(str(route)+'-timing')/'graph-pcout-0-carry-0.1.tsv';out=a.out.resolve();out.mkdir(exist_ok=False)
source=root/'build-dsp-preg-timing/ds182.txt';section=source.read_text().split('Table 31: CLB Switching Characteristics',1)[1].split('Table 32:',1)[0];values={}
for symbol in ['TCKO','TSHCKO']:
 line=next(v for v in section.splitlines() if v.startswith(symbol+' '));xs=re.findall(r'\d+\.\d+',line);assert len(xs)==6;values[symbol]=float(xs[1])
assert values=={'TCKO':.27,'TSHCKO':.32};cells=json.loads((route/'routed.json').read_text())['modules']['top']['cells'];count=Counter();outgraph=out/'mapped-graph.tsv'
with graph.open() as src,outgraph.open('w') as dst:
 assert next(src).rstrip()=='VERSION\t1';dst.write('VERSION\t1\n')
 for line in src:
  v=line.rstrip('\n').split('\t')
  if v[0]=='CLOCK' and v[1] in cells and cells[v[1]]['type']=='SLICE_FFX' and v[2]=='Q':
   assert abs(float(v[8])-.1)<1e-6
   bel=cells[v[1]]['attributes']['NEXTPNR_BEL'].rsplit('/',1)[1]
   assert re.fullmatch(r'[ABCD](?:5)?FF',bel),bel
   kind='TSHCKO' if '5FF' in bel else 'TCKO';v[8]=str(values[kind]);count[kind]+=1
  dst.write('\t'.join(v)+'\n')
assert count=={'TCKO':11225,'TSHCKO':3143},count
analysis=analyze(outgraph);assert not analysis['unresolved_nodes'];(out/'analysis.json').write_text(json.dumps(analysis,indent=2)+'\n')
record=dict(cq_ns=values,output_counts=dict(count),maxima=analysis['maxima'],scope='Placed FF output CQ sensitivity only. Backend maps 5FF fabric Q through OUTMUX; DS182 -2/1.0V TSHCKO used for those. Standard FF uses TCKO. Setup, cell/route delay, clock skew, hold, DDR IO and physical corner remain unvalidated.',physical_timing_accepted=False,sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in [graph,route/'routed.json',source,outgraph,Path(__file__).resolve()]});(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'output_counts':dict(count),'worst_ns':max(v['arrival_ns'] for v in analysis['maxima']),'physical_timing_accepted':False}))
