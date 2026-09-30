"""Reconcile native omissions with expanded model evidence; never waive signoff gaps."""
import argparse,json
from collections import Counter,defaultdict
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);a=p.parse_args();r=a.route.resolve();t=Path(str(r)+'-timing');n=Path(str(r)+'-normalized');c=Path(str(r)+'-coverage');coverage=c/'native-port-coverage.json';graph=t/'graph-pcout-0-carry-0.1.tsv';sm=t/'manifest.json';manifest=json.loads(sm.read_text());variant=next(v for v in manifest['variants'] if v['symbolic_pcout_ns']==0 and v['symbolic_carry_arc_ns']==.1);assert digest(graph)==variant['graph_sha256']
ports={};clocks=defaultdict(list);clock_refs=set();cell_in=Counter();cell_out=Counter();net_in=Counter();net_out=Counter()
for line in graph.open():
 v=line.rstrip('\n').split('\t')
 if v[0]=='PORT':ports[v[1],v[3]]=v
 elif v[0]=='CLOCK':clocks[v[1],v[2]].append(v);clock_refs.add((v[1],v[4]))
 elif v[0]=='CELLARC':cell_out[v[1],v[2]]+=1;cell_in[v[1],v[3]]+=1
 elif v[0]=='NETARC':net_out[v[2],v[3]]+=1;net_in[v[4],v[5]]+=1
lp=t/'lutram-coverage.json';bp=n/'bram-decisions.json';decisions={(v['cell'],v['port']):v for v in json.loads(lp.read_text())['decisions']};decisions.update({(v['cell'],v['port']):v for v in json.loads(bp.read_text())});native=json.loads(coverage.read_text());records=[]
for v in native['ignored_dynamic_ports']:
 key=v['cell'],v['port'];assert key in ports;cls=int(ports[key][5]);d=decisions.get(key);category='unresolved';evidence=[]
 if cls==2 and clocks[key] and net_in[key]:category='expanded_setup_endpoint';evidence=['CLOCK setup record','routed incoming NETARC']
 elif cls in [3,5] and clocks[key]:category='expanded_clocked_output';evidence=['CLOCK launch record']
 elif cls==4 and cell_out[key] and net_in[key]:category='expanded_combinational_input';evidence=['CELLARC fanout','routed incoming NETARC']
 elif cls==5 and cell_in[key]:category='expanded_combinational_output';evidence=['CELLARC input']
 elif cls==0 and key in clock_refs:category='expanded_clock_reference';evidence=['clock pin referenced by CLOCK checks']
 elif d and d['reason'] in ['unobserved_RAM_half_no_output','shared_unused_read_input','inactive_B_or_bypassed_output_register']:
  category='explicit_memory_model_exclusion';evidence=[d['reason']]
 records.append(dict(cell=v['cell'],port=v['port'],type=v['type'],expanded_class=cls,category=category,evidence=evidence,physical_timing_validated=False))
assert len(records)==len(native['ignored_dynamic_ports']);counts=Counter(v['category'] for v in records);unresolved=Counter(v['type'] for v in records if v['category']=='unresolved');out=r/'expanded-port-reconciliation.json';assert not out.exists();files=[coverage,graph,sm,lp,bp,Path(__file__).resolve()];record=dict(passed=True,scope='Evidence inventory only: modeled does not mean physically validated; explicit memory-model exclusions are not newly introduced false paths.',native_ignored_dynamic_count=len(records),categories=dict(counts),unresolved_by_type=dict(unresolved),records=records,all_ports_physically_validated=False,full_soc_timing_accepted=False,sha256={str(p):digest(p) for p in files});out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record[k] for k in ['native_ignored_dynamic_count','categories','unresolved_by_type']}))
