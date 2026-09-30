"""Require SAT to reject actual truth-table corruption of either OR partition LUT."""
import argparse,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();patch=json.loads(a.patch.read_text());proof=patch['partition_proof'];out=a.out.resolve();assert not out.exists()
for n,h in proof['sha256'].items():assert digest(n)==h,n
text=Path(proof['miter']).read_text();head,candidate=text.split('module candidate',1);hits=list(re.finditer(r"\.INIT\((\d+)'b([01]+)\)",candidate));assert len(hits)==2;out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';paths=[a.patch,Path(proof['miter']),tool,lib,Path(__file__)];checks=[]
for i,hit in enumerate(hits):
 old=hit.group(2);new=old[:-1]+str(1-int(old[-1]));bad=head+'module candidate'+candidate[:hit.start(2)]+new+candidate[hit.end(2):];v=out/f'wrong-lut-{i}.v';v.write_text(bad);ys=v.with_suffix('.ys');ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=v.with_suffix('.log')
 with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
 assert rc!=0 and 'proof did fail' in log.read_text();paths.extend([v,ys,log]);checks.append(dict(lut=i,rejected=True))
(out/'manifest.json').write_text(json.dumps(dict(passed=True,checks=checks,sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print('Both actual LUT corruptions rejected by SAT.')
