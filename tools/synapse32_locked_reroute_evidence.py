"""Audit unchanged reroute: exact functional routes, only ground-route additions allowed."""
import argparse,copy,json
from collections import Counter
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells

def routes(m):
 out={}
 for n,v in m['netnames'].items():
  text=v.get('attributes',{}).get('ROUTING','').strip()
  if text:
   p=text.split(';');assert len(p)%3==0;out[n]={(p[i],p[i+1]) for i in range(0,len(p),3)}
 return out

def check_routes(a,b,ground_is_zero):
 assert ground_is_zero and set(a)==set(b)
 assert all(a[n]==b[n] for n in a if n!='$PACKER_GND_NET')
 assert a['$PACKER_GND_NET']<=b['$PACKER_GND_NET']
 return len(b['$PACKER_GND_NET']-a['$PACKER_GND_NET'])

def main():
 p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--control',type=Path,required=True);p.add_argument('--out',type=Path,required=True);x=p.parse_args();assert not x.out.exists();record=json.loads((x.control/'manifest.json').read_text());assert record['exit_code']==0 and record['inputs_unchanged'] and record['logical_ports_exact'] and record['bels_exact']
 for key in ['sha256','output_sha256']:
  for n,h in record[key].items():assert digest(n)==h,n
 a=json.loads((x.parent/'routed.json').read_text());b=json.loads((x.control/'routed.json').read_text());assert functional_cells(a)[0]==functional_cells(b)[0]
 am,bm=a['modules']['top'],b['modules']['top']
 assert {n:c['attributes'].get('NEXTPNR_BEL') for n,c in am['cells'].items()}=={n:c['attributes'].get('NEXTPNR_BEL') for n,c in bm['cells'].items()}
 for m in [am,bm]:
  bits=m['netnames']['$PACKER_GND_NET']['bits'];assert len(bits)==1
  drivers=[(n,c['type'],port) for n,c in m['cells'].items() for port,bs in c['connections'].items() if c['port_directions'][port]=='output' and bits[0] in bs]
  assert drivers==[('$PACKER_GND_DRV','PSEUDO_GND','Y')]
 ar,br=routes(am),routes(bm);added=check_routes(ar,br,True)
 graph_a=x.parent/'guidance-timing-graph.tsv';graph_b=x.control/'guidance-timing-graph.tsv';assert Counter(graph_a.read_text().splitlines())==Counter(graph_b.read_text().splitlines())
 rejected=[]
 for case in ['signal_route_change','ground_route_removed','wrong_constant']:
  bad={n:set(v) for n,v in br.items()};zero=True
  if case=='signal_route_change':name=next(n for n in ar if n!='$PACKER_GND_NET');bad[name].add(('invalid-wire','invalid-pip'))
  elif case=='ground_route_removed':bad['$PACKER_GND_NET'].remove(next(iter(ar['$PACKER_GND_NET'])))
  else:zero=False
  try:check_routes(ar,bad,zero)
  except AssertionError:rejected.append(case)
  else:raise AssertionError('Accepted invalid route control '+case)
 files=[x.parent/'iteration-integrity.json',x.parent/'routed.json',x.control/'manifest.json',x.control/'routed.json',graph_a,graph_b,Path(__file__)];assert json.loads((x.parent/'iteration-integrity.json').read_text())['passed'];result=dict(passed=True,scope='Unchanged reroute preserves every non-ground route and complete timing-graph row multiset. Only additional connections to the same verified PSEUDO_GND driver are permitted; no route removals or signal changes.',all_routes_byte_exact=False,signal_and_clock_routes_exact=True,ground_connections_added=added,timing_graph_multiset_exact=True,logical_ports_exact=True,placement_exact=True,negative_controls_rejected=rejected,full_soc_timing_accepted=False,sha256={str(q.resolve()):digest(q) for q in files});x.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='sha256'}))
if __name__=='__main__':main()
