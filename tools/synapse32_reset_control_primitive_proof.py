"""Check the reset control replacement against actual LUT primitive models."""
import copy,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import emit,logical
root=Path(__file__).resolve().parents[1];p=root/'build-grade2-reset-control-cone-proof/proof.json';proof=json.loads(p.read_text());assert proof['passed'] and proof['exhaustive_cases']==32
for path,h in proof['sha256'].items():assert digest(path)==h
old=proof['old'];new=proof['new_root'];cuts=proof['leaves'];bit=logical(next(iter(new.values())))[1]['O'];out=root/'build-grade2-reset-control-primitive-proof';out.mkdir(exist_ok=False)
tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';files=[p,tool,lib,Path(__file__).resolve()]
for label,mutate in [('candidate',False),('negative',True)]:
 candidate=copy.deepcopy(new)
 if mutate:
  c=next(iter(candidate.values()));c['parameters']['INIT']=format(int(c['parameters']['INIT'],2)^1,'032b')
 v=out/(label+'.v');v.write_text(emit(old,cuts,[bit],'gold')+'\n'+emit(candidate,cuts,[bit],'candidate')+'\nmodule proof(input [4:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n');ys=out/(label+'.ys');ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/(label+'.log')
 with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
 assert (rc==0 and 'SUCCESS!' in log.read_text()) if not mutate else (rc!=0 and 'proof did fail' in log.read_text())
 files.extend([v,ys,log])
r=dict(passed=True,primitive_sat_passed=True,negative_control_passed=True,cone_proof=str(p),added_latency_cycles=0,full_soc_timing_accepted=False,sha256={str(q):digest(q) for q in files});(out/'proof.json').write_text(json.dumps(r,indent=2)+'\n');print('PASS primitive SAT and changed-function negative control')
