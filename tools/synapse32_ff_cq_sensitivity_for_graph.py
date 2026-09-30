"""DS182-informed FF CQ sensitivity, not a complete primitive timing model."""
import argparse,json,re,hashlib
from pathlib import Path
from synapse32_analyze_timing_endpoints import analyze
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--graph',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();root=Path(__file__).resolve().parents[1];source=args.graph.resolve();ds=root/'build-dsp-preg-timing/ds182.txt';out=args.out.resolve();out.mkdir(exist_ok=False)
section=ds.read_text().split('Table 31: CLB Switching Characteristics',1)[1].split('Table 32:',1)[0]
values={}
for symbol in ['TCKO','TSHCKO']:
 line=next(l for l in section.splitlines() if l.startswith(symbol+' '));numbers=re.findall(r'\d+\.\d+',line);assert len(numbers)==6;values[symbol]=float(numbers[1])
assert values=={'TCKO':.27,'TSHCKO':.32}
rows=[l.rstrip('\n').split('\t') for l in source.open()];types={v[1]:v[2] for v in rows if v[0]=='PORT'};records=[]
for symbol,cq in values.items():
 dest=out/f'graph-{symbol}.tsv';count=0
 with dest.open('w') as f:
  for old in rows:
   v=old.copy()
   if v[0]=='CLOCK' and types[v[1]]=='SLICE_FFX' and v[2]=='Q':
    assert abs(float(v[8])-.1)<1e-6;v[8]=str(cq);count+=1
   f.write('\t'.join(v)+'\n')
 assert count>0
 a=analyze(dest);assert not a['unresolved_nodes'];(out/f'analysis-{symbol}.json').write_text(json.dumps(a,indent=2)+'\n')
 records.append({'symbol':symbol,'cq_ns':cq,'changed_ff_outputs':count,'maxima':a['maxima']})
r={'variants':records,'scope':'Uniform FF output CQ sensitivity using DS182 -2 1.0 V bounds. Actual AQ versus mux output mapping and other primitive/route/skew/hold bounds remain unvalidated; no physical Fmax claim. Setup and all routed arcs unchanged.','full_soc_timing_accepted':False,'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,ds,Path(__file__).resolve()]}}
(out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(records,indent=2))
