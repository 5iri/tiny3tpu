#!/usr/bin/env python3
"""Exhaustively checked LUT cuts at measured failing FF setup endpoints."""
import argparse,copy,hashlib,json
from pathlib import Path
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--hotspots',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--limit',type=int,default=12);a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists();source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];hotspots=json.loads(a.hotspots.read_text())
for n,h in hotspots['sha256'].items():assert digest(n)==h
assert (parent/'iteration-integrity.json').exists()
luts={n:c for n,c in cells.items() if c['type'] in [f'LUT{i}' for i in range(1,7)]};drivers={c['connections']['O'][0]:n for n,c in luts.items()};assert len(drivers)==len(luts)
def cut(cone):
 outputs={luts[n]['connections']['O'][0] for n in cone};inputs={b for n in cone for p,bs in luts[n]['connections'].items() if p!='O' for b in bs};assert not inputs.intersection({'x','z'})
 return inputs-outputs-{'0','1'}
def depth(root,cone):
 return 1+max([depth(drivers[b],cone) for p,bs in luts[root]['connections'].items() if p!='O' for b in bs if b in drivers and drivers[b] in cone] or [0])
def evaluate(bit,values,cone):
 if bit in values:return values[bit]
 if bit in ['0','1']:return int(bit)
 name=drivers[bit];assert name in cone;c=luts[name];width=int(c['type'][3:]);idx=sum(evaluate(c['connections'][f'I{i}'][0],values,cone)<<i for i in range(width));return (int(c['parameters']['INIT'],2)>>idx)&1
roots={}
for e in hotspots['endpoints']:
 c=cells.get(e['cell']);port=e['port']
 if c is None or not c['type'].startswith('FD'):continue
 if port=='SR':port=next(p for p in ['R','S','CLR','PRE'] if p in c['connections'])
 bs=c['connections'].get(port,[])
 if len(bs)==1 and bs[0] in drivers:roots.setdefault(drivers[bs[0]],e)
changes=[]
for root,endpoint in roots.items():
 pending=[frozenset([root])];seen=set();best=pending[0]
 while pending and len(seen)<512:
  cone=pending.pop()
  if cone in seen:continue
  seen.add(cone);leaves=cut(cone)
  if (depth(root,cone),len(cone))>(depth(root,best),len(best)):best=cone
  if len(cone)>=12:continue
  for bit in sorted(leaves):
   if bit not in drivers:continue
   nxt=cone|{drivers[bit]}
   if len(cut(nxt))<=6:pending.append(nxt)
 if depth(root,best)<2:continue
 leaves=sorted(cut(best));assert 1<=len(leaves)<=6
 original=cells[root];output=original['connections']['O'][0];truth=[evaluate(output,{b:(word>>i)&1 for i,b in enumerate(leaves)},best) for word in range(64)];mask=sum(v<<i for i,v in enumerate(truth));new=copy.deepcopy(original);new['type']='LUT6';new['parameters']={'INIT':format(mask,'064b')};new['connections']={**{f'I{i}':[leaves[i] if i<len(leaves) else '0'] for i in range(6)},'O':[output]};new['port_directions']={p:('output' if p=='O' else 'input') for p in new['connections']}
 changes.append(dict(target=root,original=original,candidate=new,cone={n:cells[n] for n in sorted(best)},leaves=leaves,truth_table=truth,old_depth=depth(root,best),new_depth=1,measured_endpoint=endpoint,examined_cuts=len(seen)))
 if len(changes)>=a.limit:break
assert changes
actual=copy.deepcopy(gold);ac=actual['modules']['kc705_synapse32_top']['cells']
for r in changes:ac[r['target']]=r['candidate']
restored=copy.deepcopy(actual)
for r in changes:restored['modules']['kc705_synapse32_top']['cells'][r['target']]=r['original']
assert restored==gold
out.mkdir();proof=out/'predicate-proof';proof.mkdir();record=dict(passed=True,claim='Each replacement is an exhaustive truth table of an original acyclic LUT cone with at most six independent inputs. New edges connect only original ancestors. Composition preserves every original output function; no state or latency changes. Unchanged intermediate cells retain their other consumers.',changes=changes,added_latency_cycles=0,sha256={str(q.resolve()):digest(q) for q in [source,a.hotspots,Path(__file__).resolve()]});(proof/'results.json').write_text(json.dumps(record,indent=2)+'\n')
board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
record=dict(passed=True,kind='collapsed_timing_lut_cones',parent=str(parent),source=str(source),proof=str(proof/'results.json'),changes=changes,added_latency_cycles=0,all_other_netlist_content_exact=True,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'iteration-integrity.json',parent/'mapping.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()});(out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps([dict(target=r['target'],old_depth=r['old_depth'],cut_inputs=len(r['leaves']),ns=r['measured_endpoint']['arrival_ns']) for r in changes]))
