"""Prove a zero-cycle OR-tree cut swap using actual packed primitives."""
import copy,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import logical,evaluate,emit
root=Path(__file__).resolve().parents[1];source=root/'build-grade2-pre-fixup-routing-control/pre-fixup.json';d=json.loads(source.read_text());cs=d['modules']['top']['cells'];early='$tiny3tpu$ddr_capture_or_233974_early';late=next(n for n in cs if '$233974.' in n and n.endswith('.mux8'));old={n:copy.deepcopy(cs[n]) for n in [early,late]};new=copy.deepcopy(old)
def pin(c,role):
 p=[p for p in c['connections'] if c['attributes'].get('X_ORIG_PORT_'+p)==role];assert len(p)==1;return p[0]
ep=pin(new[early],'I2');lp=pin(new[late],'I4');eb=new[early]['connections'][ep];lb=new[late]['connections'][lp];assert eb==[101596] and lb==[101539];new[early]['connections'][ep]=lb;new[late]['connections'][lp]=eb
outbit=logical(old[late])[1]['O'];mid=logical(old[early])[1]['O'];cuts=sorted({b for c in old.values() for k,b in logical(c)[1].items() if k!='O'}-{mid});assert len(cuts)==8
for word in range(256):
 values={b:(word>>i)&1 for i,b in enumerate(cuts)}
 def run(cells):
  v=dict(values)
  for c in cells.values():v[logical(c)[1]['O']]=evaluate(c,v)
  return v[outbit]
 assert run(old)==run(new)==int(word!=0)
mutant=copy.deepcopy(new);v=mutant[late]['parameters']['INIT'];mutant[late]['parameters']['INIT']=v[:-1]+('1' if v[-1]=='0' else '0');values={b:0 for b in cuts};assert run(old)!=run(mutant)
out=root/'build-grade2-readvalid-arrival-swap-proof';assert not out.exists();out.mkdir();v=out/'miter.v';v.write_text(emit(old,cuts,[outbit],'gold')+'\n'+emit(new,cuts,[outbit],'candidate')+'\nmodule proof(input [7:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n');tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/'prove.log'
with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
assert 'SUCCESS!' in log.read_text();record=dict(passed=True,source=str(source),old=old,new=new,exhaustive_cases=256,primitive_sat_passed=True,negative_control_passed=True,added_latency_cycles=0,added_cells=0,removed_cells=0,full_soc_timing_accepted=False,sha256={str(p):digest(p) for p in [source,v,ys,log,tool,lib,Path(__file__).resolve()]});(out/'proof.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS 256 input combinations, primitive SAT and changed-function negative control; candidate not routed')
