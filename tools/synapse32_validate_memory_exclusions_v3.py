"""Verify existing memory exclusions against routed connectivity and primitive profiles."""
import copy,json
from collections import defaultdict,Counter
from pathlib import Path
from synapse32_apply_bram_timing import digest,check_profile
root=Path(__file__).resolve().parents[1];r=root/'build-grade2-incremental-readvalid-arrival-swap';rp=r/'routed.json';cp=r/'expanded-port-reconciliation.json';mod=json.loads(rp.read_text())['modules']['top'];cs=mod['cells'];consumers=Counter();drivers=defaultdict(list)
for n,c in cs.items():
 for p,bs in c['connections'].items():
  if c['port_directions'][p]=='input':consumers.update(bs)
  elif c['port_directions'][p]=='output':
   for b in bs:drivers[b].append((n,p))
graph=Path(str(r)+'-timing')/'graph-pcout-0-carry-0.1.tsv';incoming={}
for line in graph.open():
 v=line.rstrip('\n').split('\t')
 if v[0]=='NETARC':incoming[v[4],v[5]]=(v[2],v[3])
representations=Counter()
def dormant_lut(c):
 assert c['type']=='SLICE_LUTX' and c['attributes'].get('X_ORIG_TYPE')=='RAMD32'
 return not any(consumers[b] for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs)
def tied_inactive_b(c,p,name=None):
 check_profile(c)
 role=c['attributes'].get('X_ORIG_PORT_'+p,'');assert role.startswith(('ADDRBWRADDR[','DIBDI[','DIPBDIP[')),role
 bs=c['connections'][p];assert len(bs)==1
 source=incoming.get((name,p))
 if source is not None:assert cs[source[0]]['type'] in ['PSEUDO_GND','PSEUDO_VCC']
 else:representations['no_graph_driver']+=1
 if not drivers[bs[0]]:representations['inactive_final_port_without_json_driver']+=1;return True
 assert len(drivers[bs[0]])==1;representations['final_constant_driver']+=1
 return cs[drivers[bs[0]][0][0]]['type'] in ['PSEUDO_GND','PSEUDO_VCC']
records=json.loads(cp.read_text())['records'];checked=[]
for v in records:
 if v['category']!='explicit_memory_model_exclusion':continue
 c=cs[v['cell']];reason=v['evidence'][0]
 assert (dormant_lut(c) if reason=='unobserved_RAM_half_no_output' else tied_inactive_b(c,v['port'],v['cell'])),v
 checked.append(v)
assert len(checked)==7994
lut=next(v for v in checked if v['type']=='SLICE_LUTX');mut=copy.deepcopy(cs[lut['cell']]);livebit=next(b for b,count in consumers.items() if count);mut['connections']['TEST_OUTPUT']=[livebit];mut['port_directions']['TEST_OUTPUT']='output';assert not dormant_lut(mut)
bram=next(v for v in checked if v['type']=='RAMB36E1_RAMB36E1');mut=copy.deepcopy(cs[bram['cell']]);mut['parameters']['WRITE_WIDTH_B']=format(2,'032b')
try:tied_inactive_b(mut,bram['port'],bram['cell'])
except AssertionError:negative_b=True
else:negative_b=False
assert negative_b
out=r/'memory-exclusion-evidence-v3.json';assert not out.exists();result=dict(passed=True,verified_excluded_ports=len(checked),bram_representation_counts=dict(representations),unobserved_lutram_cells=len({v['cell'] for v in checked if v['type']=='SLICE_LUTX'}),inactive_bram_cells=len({v['cell'] for v in checked if v['type']=='RAMB36E1_RAMB36E1'}),negative_controls_passed=True,scope='Existing exclusions only: no LUTRAM output consumer; BRAM B disabled; any graph ties must come from actual constant primitives; absent graph drivers are counted. Final JSON may leave disabled B inputs undriven; these are counted explicitly. No new false paths or physical signoff.',full_soc_timing_accepted=False,sha256={str(p):digest(p) for p in [rp,cp,graph,Path(__file__).resolve(),root/'tools/synapse32_apply_bram_timing.py']});out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='sha256'}))
