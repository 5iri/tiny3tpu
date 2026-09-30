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
 assert mapping['kind']=='collapsed_sequencer_mux_lut'
 sm=source['modules']['kc705_synapse32_top'];am=actual['modules']['kc705_synapse32_top'];rm=restored['modules']['kc705_synapse32_top']
 target=mapping['target'];assert sm['cells'][target]==mapping['original_cell'] and am['cells'][target]==mapping['candidate_cell']==proof['replacement']
 assert all(sm['cells'][n]==cell for n,cell in proof['cone'].items())
 replacement=proof['replacement'];assert replacement['type']=='LUT6' and replacement['connections']['O']==mapping['original_cell']['connections']['O']
 leaves=proof['leaves'];assert len(leaves)==6 and all(replacement['connections'][f'I{i}']==[b] for i,b in enumerate(leaves))
 drivers={cell['connections']['O'][0]:cell for cell in proof['cone'].values()}
 assert len(drivers)==len(proof['cone'])==3
 assert sorted(cell['type'] for cell in proof['cone'].values())==['LUT4','LUT4','MUXF7']
 assert set(leaves)=={b for cell in proof['cone'].values() for port,bs in cell['connections'].items() if port!='O' for b in bs}-drivers.keys()
 def evaluate(bit,values):
  if bit in values:return values[bit]
  cell=drivers[bit]
  if cell['type']=='MUXF7':
   x=evaluate(cell['connections']['I0'][0],values);y=evaluate(cell['connections']['I1'][0],values);s=evaluate(cell['connections']['S'][0],values)
   return (x & (1-s)) | (y & s)
  assert cell['type'] in ['LUT4'];width=int(cell['type'][3:]);idx=sum(evaluate(cell['connections'][f'I{i}'][0],values)<<i for i in range(width));return (int(cell['parameters']['INIT'],2)>>idx)&1
 for word in range(64):
  truth=evaluate(replacement['connections']['O'][0],{b:(word>>i)&1 for i,b in enumerate(leaves)})
  assert truth==proof['truth_table'][word]==((int(replacement['parameters']['INIT'],2)>>word)&1)
 rm['cells'][target]=mapping['original_cell']
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
  scope='Actual parent synthesis/workloads and proved DSP mapping composed with an exhaustively proved six-input sequencer LUT/MUXF7 collapse, then fresh placement/routing and independently checked timing. All other netlist content, firmware and constraints are unchanged. Timing remains unaccepted; generic delays, clocks, hold/reset and DDR IO are not fully validated.',firmware_identical=True,constraints_identical=True,
  expanded_intervals_ns=[max(x['arrival_ns'] for x in v['maxima']) for v in model['variants']],focused_intervals_ns={k:v['worst_ns'] for k,v in focus['results'].items()},full_soc_timing_accepted=False,checked_manifests=records,sha256={str(q.resolve()):digest(q) for q in [Path(__file__),dsp]})
 a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['passed','expanded_intervals_ns','full_soc_timing_accepted']}))
if __name__=='__main__':main()
