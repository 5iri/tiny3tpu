"""Reject initialization, reset and constant-cone defects in the actual timer proof."""
import argparse,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());proof=patch['timer_proof']
for n,h in proof['sha256'].items():assert digest(n)==h,n
source=Path(proof['miter']);text=source.read_text();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';out=a.out.resolve();out.mkdir();cases={
'wrong_flag_init':("FDRE #(.INIT(1'b0)) f", "FDRE #(.INIT(1'b1)) f"),
'ignored_flag_reset':(".R(rst),.CE(1'b1),.D(fd)", ".R(1'b0),.CE(1'b1),.D(fd)"),
'wrong_ground':("gold g({1'b0,q},expected)","gold g({1'b1,q},expected)")};records=[];paths=[a.patch,source,tool,lib,Path(__file__)]
for name,(old,new) in cases.items():
 assert text.count(old)==1;v=out/(name+'.v');v.write_text(text.replace(old,new));ys=out/(name+'.ys');ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -seq 4 -prove same 1 -verify\n');log=out/(name+'.log')
 with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
 assert rc!=0 and 'proof did fail' in log.read_text(),name;records.append(dict(name=name,rejected=True,exit_code=rc));paths.extend([v,ys,log])
(out/'negative-checks.json').write_text(json.dumps(dict(passed=True,actual_primitive_corruptions_rejected=records,sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print(json.dumps(records))
