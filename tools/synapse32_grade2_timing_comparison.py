#!/usr/bin/env python3
"""Ensure grade selection changes only clock timing values on modeled primitives."""
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--all-grades',type=Path,required=True);p.add_argument('--grade2',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();old=json.loads((a.all_grades/'manifest.json').read_text());new=json.loads((a.grade2/'manifest.json').read_text());assert new['grade_selection'];checked=[]
for folder,d in [(a.all_grades,old),(a.grade2,new)]:
 for n,h in d['sha256'].items():assert digest(n)==h
 checked.append(dict(path=str((folder/'manifest.json').resolve()),sha256=digest(folder/'manifest.json')))
route_paths=[n for n in old['sha256'] if n.endswith('/routed.json')];assert len(route_paths)==1;route=route_paths[0];assert new['sha256'][route]==old['sha256'][route]
cells=next(iter(json.loads(Path(route).read_text())['modules'].values()))['cells'];variants=[]
for ov,nv in zip(old['variants'],new['variants']):
 assert (ov['symbolic_pcout_ns'],ov['symbolic_carry_arc_ns'])==(nv['symbolic_pcout_ns'],nv['symbolic_carry_arc_ns'])
 name=f"graph-pcout-{ov['symbolic_pcout_ns']}-carry-{ov['symbolic_carry_arc_ns']}.tsv";op=a.all_grades/name;np=a.grade2/name;assert digest(op)==ov['graph_sha256'] and digest(np)==nv['graph_sha256'];changed=0;count=0
 with op.open() as f,np.open() as g:
  for first,second in zip(f,g,strict=True):
   count+=1
   if first==second:continue
   x=first.rstrip('\n').split('\t');y=second.rstrip('\n').split('\t');assert x[0]==y[0]=='CLOCK' and x[:6]==y[:6] and x[9:]==y[9:]
   cell=cells[x[1]];assert cell['type'] in ['DSP48E1_DSP48E1','RAMB36E1_RAMB36E1'] or (cell['type']=='SLICE_LUTX' and cell['attributes'].get('X_LUT_AS_DRAM','').strip()=='1')
   assert all(float(b)<=float(a)+1e-9 for a,b in zip(x[6:9],y[6:9]));changed+=1
 variants.append(dict(pcout_ns=ov['symbolic_pcout_ns'],carry_ns=ov['symbolic_carry_arc_ns'],rows=count,changed_clock_values=changed,all_grades_ns=max(e['arrival_ns'] for e in ov['maxima']),grade2_ns=max(e['arrival_ns'] for e in nv['maxima'])))
 assert variants[-1]['grade2_ns']<=variants[-1]['all_grades_ns']
record=dict(passed=True,claim='Exact same routed design, ports, net arcs, combinational arcs and symbolic probes. Only clock setup/hold/CQ values on the same modeled registered DSP/RAM/LUTRAM profiles differ. This is a model comparison, not a new placement or hardware speedup.',variants=variants,checked_manifests=checked,sha256={str(Path(__file__).resolve()):digest(__file__)},full_soc_timing_accepted=False);a.out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(variants))
