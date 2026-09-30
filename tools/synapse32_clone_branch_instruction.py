#!/usr/bin/env python3
"""Replicate existing instruction registers only for local branch-decode consumers."""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
 mapping=json.loads((parent/'mapping.json').read_text());prior=json.loads((parent/'iteration-integrity.json').read_text());assert mapping['passed'] and prior['passed'] and mapping['kind']=='factored_guarded_branch_predicate'
 for d in [mapping,prior]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h
 source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];ids=m['netnames']['soc.cpu.ex_unit_inst0.alu_inst.instr_id']['bits'];assert len(ids)==7
 allbits={b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}|{b for c in m['netnames'].values() for b in c['bits'] if isinstance(b,int)}|{b for c in m['ports'].values() for b in c['bits'] if isinstance(b,int)};fresh=max(allbits)+1
 actual=copy.deepcopy(gold);am=actual['modules']['kc705_synapse32_top'];ac=am['cells'];clones=[];changes={};netnames={}
 for i,bit in enumerate(ids):
  matches=[(n,c) for n,c in cells.items() if c['connections'].get('Q')==[bit] and c['port_directions'].get('Q')=='output'];assert len(matches)==1;name,original=matches[0]
  assert original['type'] in ['FDCE','FDPE'] and original['parameters']=={'INIT':'x'} and original['connections']['CE']==['1']
  assert original['connections']['C']==[38962] and original['connections']['CLR' if original['type']=='FDCE' else 'PRE']==[725]
  clone=copy.deepcopy(original);clone_name=f'$tiny3tpu$branch_instr_local_{i}';assert clone_name not in ac;clone['connections']['Q']=[fresh+i];clone['attributes']['keep']='1';ac[clone_name]=clone
  netname=f'branch_instr_local[{i}]';assert netname not in am['netnames'];net=dict(hide_name=0,bits=[fresh+i],attributes={});am['netnames'][netname]=net;netnames[netname]=net
  consumers=[]
  for target in mapping['added']:
   for port,bs in cells[target]['connections'].items():
    if cells[target]['port_directions'][port]=='input' and bit in bs:
     assert bs==[bit];changes.setdefault(target,dict(original=cells[target]));ac[target]['connections'][port]=[fresh+i];consumers.append([target,port])
  assert consumers;clones.append(dict(original_name=name,original=original,name=clone_name,cell=clone,consumers=consumers))
 for n,r in changes.items():r['candidate']=ac[n]
 restored=copy.deepcopy(actual);rm=restored['modules']['kc705_synapse32_top']
 for r in clones:del rm['cells'][r['name']]
 for n in netnames:del rm['netnames'][n]
 for n,r in changes.items():rm['cells'][n]=r['original']
 assert restored==gold
 out.mkdir();proof=out/'predicate-proof';proof.mkdir();yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v'
 for kind,reset in [('FDCE','CLR'),('FDPE','PRE')]:
  v=proof/f'{kind}.v';v.write_text(f"module proof(input clk,rst,d,output same);wire q1,q2;{kind} #(.INIT(1'bx)) gold(.C(clk),.CE(1'b1),.{reset}(rst),.D(d),.Q(q1));{kind} #(.INIT(1'bx)) clone(.C(clk),.CE(1'b1),.{reset}(rst),.D(d),.Q(q2));assign same=q1==q2;endmodule\n")
  ys=proof/f'{kind}.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof; flatten; async2sync; opt; check -assert; sat -seq 4 -set-at 1 rst 1 -prove-skip 1 -prove same 1 -verify; sat -seq 3 -set-init-zero -tempinduct -maxsteps 8 -prove same 1 -verify;\n')
  with (proof/f'{kind}.log').open('w') as log:subprocess.run([str(yosys),'-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True)
 paths=[source,Path(__file__).resolve(),yosys,lib]+list(proof.iterdir());record=dict(passed=True,claim='Seven exact FDCE/FDPE replicas, same C/CE/D/asynchronous reset/INIT. Actual primitive reset-sequence proof plus temporal induction from a common state, with arbitrary subsequent data/reset. Unknown initial states before reset and analog reset recovery/removal are not claimed. Only six local branch LUT consumers move; no new pipeline stage or edge.',added_latency_cycles=0,sha256={str(q):digest(q) for q in paths});(proof/'results.json').write_text(json.dumps(record,indent=2)+'\n')
 board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
 for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
 record=dict(passed=True,kind='local_branch_instruction_replicas',parent=str(parent),source=str(source),proof=str(proof/'results.json'),clones=clones,changes=changes,added_netnames=netnames,added_latency_cycles=0,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'mapping.json',parent/'iteration-integrity.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()});(out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS seven local instruction FF replicas; same edge, primitive reset/induction proofs')
if __name__=='__main__':main()
