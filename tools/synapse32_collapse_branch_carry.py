#!/usr/bin/env python3
"""Collapse the two surviving instruction-only carry/decode cuts to exact LUT6s."""
import argparse,copy,json,subprocess
from pathlib import Path
from synapse32_factor_branch_predicate import digest,drivers_of,evaluate,verilog

def main():
 p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
 source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];drivers=drivers_of(cells)
 ids=m['netnames']['soc.cpu.ex_unit_inst0.alu_inst.instr_id']['bits'];conditions=[m['netnames']['soc.cpu.ex_unit_inst0.'+n]['bits'][0] for n in ['branch_equal','branch_less_signed','branch_less_unsigned']];leaves=ids+conditions;assert len(leaves)==10
 actual=copy.deepcopy(gold);changes=[]
 for root in [8239,8238]:
  name,old,port,index=drivers[root];assert old['type']=='LUT6' and port=='O';seen=set()
  truth=[evaluate(root,{b:(w>>i)&1 for i,b in enumerate(leaves)},drivers,seen) for w in range(1024)]
  support=[i for i in range(10) if any(truth[w]!=truth[w^(1<<i)] for w in range(1024))];assert len(support)==6
  inputs=[leaves[i] for i in support];mask=sum(truth[sum(((w>>i)&1)<<j for i,j in enumerate(support))]<<w for w in range(64))
  new=copy.deepcopy(old);new['parameters']={'INIT':format(mask,'064b')};new['connections']={**{f'I{i}':[b] for i,b in enumerate(inputs)},'O':[root]}
  for w,v in enumerate(truth):assert ((mask>>sum(((w>>j)&1)<<i for i,j in enumerate(support)))&1)==v
  actual['modules']['kc705_synapse32_top']['cells'][name]=new
  changes.append(dict(target=name,root=root,original=old,candidate=new,cone={n:cells[n] for n in sorted(seen)},support=support,truth_table=truth))
 restored=copy.deepcopy(actual)
 for r in changes:restored['modules']['kc705_synapse32_top']['cells'][r['target']]=r['original']
 assert restored==gold
 out.mkdir();proof=out/'predicate-proof';proof.mkdir();yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v'
 for r in changes:
  root=r['root'];v=proof/f'{root}.v';v.write_text(verilog(r['cone'],leaves,root,'gold')+'\n'+verilog({r['target']:r['candidate']},leaves,root,'candidate')+'\nmodule miter(input [9:0] x,output equal);wire a,b;gold g(x,a);candidate c(x,b);assign equal=a==b;endmodule\n')
  ys=proof/f'{root}.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top miter; flatten; opt; check -assert; sat -verify -prove equal 1 -show-inputs;\n')
  with (proof/f'{root}.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 paths=[source,yosys,lib,Path(__file__).resolve(),Path(__file__).with_name('synapse32_factor_branch_predicate.py').resolve()]+list(proof.iterdir())
 record=dict(passed=True,claim='Each actual carry/LUT cone depends on only six of ten arbitrary instruction/condition inputs. All 1024 cases per root and actual-primitive SAT agree with one LUT6 per root. Only two existing cells change; no state, latency or other consumer changes.',leaves=leaves,changes=changes,added_latency_cycles=0,sha256={str(q):digest(q) for q in paths});(proof/'results.json').write_text(json.dumps(record,indent=2)+'\n')
 board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
 for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
 record=dict(passed=True,kind='collapsed_branch_carry_cuts',parent=str(parent),source=str(source),proof=str(proof/'results.json'),changes=changes,added_latency_cycles=0,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'mapping.json',parent/'iteration-integrity.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()});(out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS 2048 cases and two primitive SAT proofs; two LUT6 replacements, no new state')
if __name__=='__main__':main()
