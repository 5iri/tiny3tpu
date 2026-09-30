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
 assert mapping['kind']=='local_branch_instruction_replicas'
 sm=source['modules']['kc705_synapse32_top'];am=actual['modules']['kc705_synapse32_top'];rm=restored['modules']['kc705_synapse32_top']
 ids=sm['netnames']['soc.cpu.ex_unit_inst0.alu_inst.instr_id']['bits'];assert len(mapping['clones'])==len(ids)==7
 old_bits={b for cell in sm['cells'].values() for bs in cell['connections'].values() for b in bs if isinstance(b,int)}|{b for v in sm['netnames'].values() for b in v['bits'] if isinstance(b,int)}|{b for v in sm['ports'].values() for b in v['bits'] if isinstance(b,int)}
 new_bits=set();expected_changes={}
 pm=check(parent/'mapping.json');assert pm['kind']=='factored_guarded_branch_predicate'
 for i,r in enumerate(mapping['clones']):
  original=sm['cells'][r['original_name']];assert original==r['original'] and original['connections']['Q']==[ids[i]]
  clone=am['cells'][r['name']];assert clone==r['cell'] and r['name'] not in sm['cells'] and clone['type'] in ['FDCE','FDPE']
  bit=clone['connections']['Q'][0];assert bit not in old_bits and bit not in new_bits;new_bits.add(bit)
  restored_clone=copy.deepcopy(clone);restored_clone['connections']['Q']=original['connections']['Q'];restored_clone['attributes']=original['attributes'];assert restored_clone==original
  assert clone['attributes']==dict(original['attributes'],keep='1') and clone['parameters']=={'INIT':'x'} and clone['connections']['CE']==['1']
  assert clone['connections']['C']==[38962] and clone['connections']['CLR' if clone['type']=='FDCE' else 'PRE']==[725]
  consumers=[]
  for target in pm['added']:
   cell=sm['cells'][target]
   for port,bs in cell['connections'].items():
    if cell['port_directions'][port]=='input' and ids[i] in bs:
     assert bs==[ids[i]];expected_changes.setdefault(target,copy.deepcopy(cell))['connections'][port]=[bit];consumers.append([target,port])
  assert r['consumers']==consumers and consumers;del rm['cells'][r['name']]
 assert set(expected_changes)==set(mapping['changes'])
 for n,r in mapping['changes'].items():
  assert r['original']==sm['cells'][n] and r['candidate']==am['cells'][n]==expected_changes[n];rm['cells'][n]=r['original']
 assert len(mapping['added_netnames'])==7
 assert {v['bits'][0] for v in mapping['added_netnames'].values()}==new_bits
 for n,v in mapping['added_netnames'].items():assert n not in sm['netnames'] and am['netnames'][n]==v;del rm['netnames'][n]
 assert restored==source
 for kind in ['FDCE','FDPE']:
  log=(Path(mapping['proof']).parent/(kind+'.log')).read_text();assert 'SUCCESS!' in log and 'Induction step proven' in log
 for name in ['firmware.hex','kc705.xdc']:assert digest(c/'board'/name)==digest(parent/'board'/name)
 route=check(a.route/'manifest.json');assert route['inputs_unchanged'] and route['timing']['completed'] and route['graph_analysis_completed']
 assert route['sha256'][str(c/'board/soc.json')]==digest(c/'board/soc.json')
 routed=json.loads((a.route/'routed.json').read_text())['modules']['top']['cells'];assert all(r['name'] in routed for r in mapping['clones'])
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
  scope='Actual parent synthesis/workloads and proved DSP mapping composed with seven same-edge local instruction FF replicas, with exact structural reconstruction and actual-primitive reset/induction proofs, then fresh placement/routing and independently checked timing. All other netlist content, firmware and constraints are unchanged. Timing remains unaccepted; generic delays, clocks, hold/reset and DDR IO are not fully validated.',firmware_identical=True,constraints_identical=True,
  expanded_intervals_ns=[max(x['arrival_ns'] for x in v['maxima']) for v in model['variants']],focused_intervals_ns={k:v['worst_ns'] for k,v in focus['results'].items()},full_soc_timing_accepted=False,checked_manifests=records,sha256={str(q.resolve()):digest(q) for q in [Path(__file__),dsp]})
 a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['passed','expanded_intervals_ns','full_soc_timing_accepted']}))
if __name__=='__main__':main()
