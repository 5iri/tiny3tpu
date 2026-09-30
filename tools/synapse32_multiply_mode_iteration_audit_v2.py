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
 assert mapping['kind']=='captured_multiplier_instruction_modes'
 sm=source['modules']['kc705_synapse32_top'];am=actual['modules']['kc705_synapse32_top'];rm=restored['modules']['kc705_synapse32_top']
 assert len(mapping['added_cells'])==8 and len(mapping['original_cells'])==3
 ids=sm['netnames']['soc.cpu.ex_unit_inst0.alu_inst.instr_id']['bits']
 regs=[sm['cells'][n] for n in mapping['instruction_registers']]
 assert [c['connections']['Q'][0] for c in regs]==ids
 clock=regs[0]['connections']['C'];enable=regs[0]['connections']['CE'];reset=regs[0]['connections'].get('PRE',regs[0]['connections'].get('CLR'))
 assert all(c['type'] in ['FDPE','FDCE'] and c['parameters']=={'INIT':'x'} and c['connections']['C']==clock and c['connections']['CE']==enable and c['connections'].get('PRE',c['connections'].get('CLR'))==reset for c in regs)
 assert sum((c['type']=='FDPE')<<i for i,c in enumerate(regs))==11
 for label,root,raw,codes in [('a',32554,7788,[49,50]),('b',32555,3484,[49])]:
  prefix='$tiny3tpu$mul_mode_'+label
  low,high,ff,sign=[am['cells'][prefix+suffix] for suffix in ['_low','_high','_q','_sign']]
  assert low['type']=='LUT6' and int(low['parameters']['INIT'],2)==sum(1<<code for code in codes)
  assert all(low['connections'][f'I{i}']==regs[i]['connections']['D'] for i in range(6))
  assert high['type']=='LUT2' and high['parameters']=={'INIT':'0010'} and high['connections']['I0']==low['connections']['O'] and high['connections']['I1']==regs[6]['connections']['D']
  assert ff['type']=='FDCE' and ff['parameters']=={'INIT':'x'} and ff['connections']==dict(C=clock,CE=enable,CLR=reset,D=high['connections']['O'],Q=ff['connections']['Q'])
  assert sign['type']=='LUT2' and sign['parameters']=={'INIT':'1000'} and sign['connections']['I0']==[raw] and sign['connections']['I1']==ff['connections']['Q']
  for n,old in mapping['original_cells'].items():
   assert old==sm['cells'][n] and old['type']=='DSP48E1'
   for port in ['A','B']:
    for i,bit in enumerate(old['connections'][port]):
     if bit==root:assert i>=16 and am['cells'][n]['connections'][port][i]==sign['connections']['O'][0]
 for n,old in mapping['original_cells'].items():
  assert am['cells'][n]==mapping['candidate_cells'][n]
  permitted=copy.deepcopy(old)
  for label,root in [('a',32554),('b',32555)]:
   replacement=am['cells']['$tiny3tpu$mul_mode_'+label+'_sign']['connections']['O'][0]
   for port in ['A','B']:permitted['connections'][port]=[replacement if b==root else b for b in permitted['connections'][port]]
  assert am['cells'][n]==permitted
  rm['cells'][n]=old
 for n,cell in mapping['added_cells'].items():
  assert n not in sm['cells'] and am['cells'][n]==cell and set(cell['connections'])<=set(cell['port_directions'])
  del rm['cells'][n]
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
  scope='Actual parent synthesis/workloads and proved DSP mapping composed with inductively proved instruction-mode captures and exhaustive original sign-cone truth tables, then fresh placement/routing and independently checked timing. All other netlist content, firmware and constraints are unchanged. Timing remains unaccepted; generic delays, clocks, hold/reset and DDR IO are not fully validated.',firmware_identical=True,constraints_identical=True,
  expanded_intervals_ns=[max(x['arrival_ns'] for x in v['maxima']) for v in model['variants']],focused_intervals_ns={k:v['worst_ns'] for k,v in focus['results'].items()},full_soc_timing_accepted=False,checked_manifests=records,sha256={str(q.resolve()):digest(q) for q in [Path(__file__),dsp]})
 a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['passed','expanded_intervals_ns','full_soc_timing_accepted']}))
if __name__=='__main__':main()
