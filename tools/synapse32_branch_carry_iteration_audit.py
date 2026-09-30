#!/usr/bin/env python3
"""Audit a derived DSP mapping, parent workloads, actual routes and expanded timing."""
import argparse,copy,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ['candidate','route','sensitivity','check','focused','out']:p.add_argument('--'+k,type=Path,required=True)
 a=p.parse_args();c=a.candidate.resolve();assert not a.out.exists();records=[];seen=set()
 def check(path):
  path=path.resolve();d=json.loads(path.read_text())
  if path in seen:return d
  seen.add(path)
  for key in ['sha256','output_sha256']:
   for n,h in d.get(key,{}).items():assert digest(n)==h,(path,n)
  for r in d.get('checked_manifests',[]):
   assert digest(r['path'])==r['sha256'];check(Path(r['path']))
  records.append(dict(path=str(path),sha256=digest(path)));return d
 mapping=check(c/'mapping.json');assert mapping['passed'] and mapping['added_latency_cycles']==0
 parent=Path(mapping['parent']);prior=check(parent/'iteration-integrity.json');assert prior['passed']
 proof=check(Path(mapping['proof']));assert proof['passed'] and proof['added_latency_cycles']==0
 source=json.loads(Path(mapping['source']).read_text());actual=json.loads((c/'board/soc.json').read_text());restored=copy.deepcopy(actual)
 assert mapping['kind']=='collapsed_branch_carry_cuts' and mapping['changes']==proof['changes'] and len(mapping['changes'])==2
 from synapse32_factor_branch_predicate import evaluate,drivers_of,verilog
 sm=source['modules']['kc705_synapse32_top'];am=actual['modules']['kc705_synapse32_top'];rm=restored['modules']['kc705_synapse32_top']
 leaves=sm['netnames']['soc.cpu.ex_unit_inst0.alu_inst.instr_id']['bits']+[sm['netnames']['soc.cpu.ex_unit_inst0.'+n]['bits'][0] for n in ['branch_equal','branch_less_signed','branch_less_unsigned']]
 assert leaves==proof['leaves'] and len(leaves)==10
 for r in mapping['changes']:
  target=r['target'];assert sm['cells'][target]==r['original'] and am['cells'][target]==r['candidate']
  assert all(sm['cells'][n]==cell for n,cell in r['cone'].items())
  new=r['candidate'];root=r['root'];assert new['type']=='LUT6' and new['connections']['O']==r['original']['connections']['O']==[root]
  support=r['support'];assert len(support)==len(set(support))==6 and all(new['connections'][f'I{i}']==[leaves[j]] for i,j in enumerate(support))
  drivers=drivers_of(r['cone']);mask=int(new['parameters']['INIT'],2)
  for word in range(1024):
   v=evaluate(root,{b:(word>>i)&1 for i,b in enumerate(leaves)},drivers,set());assert v==r['truth_table'][word]==((mask>>sum(((word>>j)&1)<<i for i,j in enumerate(support)))&1)
  expected=verilog(r['cone'],leaves,root,'gold')+'\n'+verilog({target:new},leaves,root,'candidate')+'\nmodule miter(input [9:0] x,output equal);wire a,b;gold g(x,a);candidate c(x,b);assign equal=a==b;endmodule\n'
  assert (Path(mapping['proof']).parent/f'{root}.v').read_text()==expected
  assert 'SUCCESS!' in (Path(mapping['proof']).parent/f'{root}.log').read_text()
  rm['cells'][target]=r['original']
 assert restored==source
 for name in ['firmware.hex','kc705.xdc']:assert digest(c/'board'/name)==digest(parent/'board'/name)
 route=check(a.route/'manifest.json');assert route['inputs_unchanged'] and route['timing']['completed'] and route['graph_analysis_completed']
 assert route['sha256'][str(c/'board/soc.json')]==digest(c/'board/soc.json')
 model=check(a.sensitivity/'manifest.json');assert model['sha256'][str(a.route.resolve()/'manifest.json')]==digest(a.route/'manifest.json')
 assert model['registered_dsp_count']==4 and model['expected_cascades']==0
 for v in model['variants']:
  q=a.sensitivity/f"graph-pcout-{v['symbolic_pcout_ns']}-carry-{v['symbolic_carry_arc_ns']}.tsv";assert digest(q)==v['graph_sha256']
 dsp=a.sensitivity/'dsp-coverage.json';coverage=json.loads(dsp.read_text())
 assert len(coverage['profiles'])==4 and not coverage['unknown_delays']
 assert all(v['kind']=='cpu_preg' and v['mode']==5 for v in coverage['profiles'].values())
 gate=check(a.check/'report.json');assert not gate['accepted'] and not gate['full_soc_timing_accepted']
 assert gate['sha256'][str(a.sensitivity.resolve()/'manifest.json')]==digest(a.sensitivity/'manifest.json')
 focus=check(a.focused);assert focus['sha256'][str(a.sensitivity.resolve()/'manifest.json')]==digest(a.sensitivity/'manifest.json')
 result=dict(passed=True,candidate=str(c),route=str(a.route.resolve()),proofs=[mapping['proof']],functional=prior['functional'],functional_test_source=prior.get('functional_test_source',str(parent)),new_rtl_synthesis_run=False,new_workload_simulation_run=False,
  scope='Actual parent synthesis/workloads and proved DSP mapping composed with two actual carry-cone to LUT6 replacements, checked over all 2048 cases and independent primitive SAT proofs, then fresh placement/routing and independently checked timing. All other netlist content, firmware and constraints are unchanged. Timing remains unaccepted; generic delays, clocks, hold/reset and DDR IO are not fully validated.',firmware_identical=True,constraints_identical=True,
  expanded_intervals_ns=[max(x['arrival_ns'] for x in v['maxima']) for v in model['variants']],focused_intervals_ns={k:v['worst_ns'] for k,v in focus['results'].items()},full_soc_timing_accepted=False,checked_manifests=records,sha256={str(q.resolve()):digest(q) for q in [Path(__file__),dsp,ROOT/'tools/synapse32_factor_branch_predicate.py']})
 a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['passed','expanded_intervals_ns','full_soc_timing_accepted']}))
if __name__=='__main__':main()
