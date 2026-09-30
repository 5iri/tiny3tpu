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
 assert mapping['kind']=='captured_zqcs_zero'
 from synapse32_capture_zqcs_zero import module,cone_for,drivers_of
 sm=source['modules']['kc705_synapse32_top'];am=actual['modules']['kc705_synapse32_top'];rm=restored['modules']['kc705_synapse32_top']
 count=sm['netnames']['memory.main_zqcs_timer_count0']['bits'];assert len(count)==27 and count==proof['count']
 controls=proof['controls'];assert controls==[1873,1880,1915,1916]
 root=proof['root'];target=mapping['target'];assert root==1870 and target==proof['target']
 assert sm['cells'][target]==mapping['original_cell'] and am['cells'][target]==mapping['candidate_cell']==proof['replacement']
 assert mapping['added']==proof['added'] and len(mapping['added'])==7
 old_bits={b for cell in sm['cells'].values() for bs in cell['connections'].values() for b in bs if isinstance(b,int)}|{b for v in sm['netnames'].values() for b in v['bits'] if isinstance(b,int)}|{b for v in sm['ports'].values() for b in v['bits'] if isinstance(b,int)}
 new_bits=[]
 for n,cell in mapping['added'].items():
  assert n not in sm['cells'] and am['cells'][n]==cell
  new_bits += [b for p,bs in cell['connections'].items() if cell['port_directions'][p]=='output' for b in bs]
  del rm['cells'][n]
 assert len(new_bits)==len(set(new_bits))==7 and not set(new_bits)&old_bits
 rm['cells'][target]=mapping['original_cell'];assert restored==source
 drivers=drivers_of(sm['cells']);counter={drivers[b][0]:drivers[b][1] for b in count};assert counter==proof['counter']
 assert proof['cone']==cone_for([root],sm['cells'],drivers,count+controls)
 assert proof['data_cone']==cone_for([cell['connections']['D'][0] for cell in counter.values()],sm['cells'],drivers,count)
 initial=0
 for i,b in enumerate(count):
  cell=drivers[b][1];assert cell['type'] in ['FDRE','FDSE'] and cell['connections']['C']==[37425] and cell['connections']['CE']==['1']
  assert cell['connections']['R' if cell['type']=='FDRE' else 'S']==[31262]
  init=int(cell['parameters']['INIT'],2);assert init==int(cell['type']=='FDSE');initial |=init<<i
 assert initial==99999999
 ff=proof['added']['$tiny3tpu$zqcs_zero_q'];flag=ff['connections']['Q'][0]
 assert ff['type']=='FDRE' and ff['parameters']=={'INIT':'0'} and ff['connections']['C']==[37425] and ff['connections']['R']==[31262] and ff['connections']['CE']==['1']
 replacement=proof['replacement'];assert replacement['type']=='LUT5' and replacement['connections']=={**{f'I{i}':[b] for i,b in enumerate([flag]+controls)},'O':[root]}
 mask=int(replacement['parameters']['INIT'],2)
 abstraction=module(proof['cone'],count+controls,[root],'gold')+f"\nmodule candidate(input [30:0] x,output y);wire z=(x[26:0]==0);LUT5 #(.INIT(32'b{mask:032b})) l(.I0(z),.I1(x[27]),.I2(x[28]),.I3(x[29]),.I4(x[30]),.O(y));endmodule\nmodule proof(input [30:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n"
 state=module({**proof['data_cone'],**counter,**proof['added']},[37425,31262],count+[flag],'state')+"\nmodule proof(input [1:0] x,output same);wire [27:0] y;state s(x,y);assign same=y[27]==(y[26:0]==0);endmodule\n"
 for name,text in [('abstraction',abstraction),('state',state)]:
  folder=Path(mapping['proof']).parent;assert (folder/(name+'.v')).read_text()==text
  assert 'SUCCESS!' in (folder/(name+'.log')).read_text()
 assert 'Induction step proven' in (Path(mapping['proof']).parent/'state.log').read_text()
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
  scope='Actual parent synthesis/workloads and proved DSP mapping composed with the DDR ZQCS timer zero flag, proved with full combinational control SAT and actual-counter primitive induction on the same counter edge, then fresh placement/routing and independently checked timing. All other netlist content, firmware and constraints are unchanged. Timing remains unaccepted; generic delays, clocks, hold/reset and DDR IO are not fully validated.',firmware_identical=True,constraints_identical=True,
  expanded_intervals_ns=[max(x['arrival_ns'] for x in v['maxima']) for v in model['variants']],focused_intervals_ns={k:v['worst_ns'] for k,v in focus['results'].items()},full_soc_timing_accepted=False,checked_manifests=records,sha256={str(q.resolve()):digest(q) for q in [Path(__file__),dsp,ROOT/'tools/synapse32_capture_zqcs_zero.py']})
 a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['passed','expanded_intervals_ns','full_soc_timing_accepted']}))
if __name__=='__main__':main()
