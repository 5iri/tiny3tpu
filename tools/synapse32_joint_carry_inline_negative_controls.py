"""Reject actual corrupted LUTs in the combined carry-buffer primitive proof."""
import argparse,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--proof',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();d=json.loads(a.proof.read_text());assert d['passed'] and d['actual_primitive_sat'];out=a.out.resolve();assert not out.exists()
for n,h in d['sha256'].items():assert digest(n)==h,n
v=a.proof.parent/'miter.v';original=v.read_text();out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';paths=[a.proof,v,Path(__file__),tool,lib];results=[]
for i in [0,d['selected_count']-1]:
 start=original.index(f'module gate{i}(');end=original.index('endmodule',start);part=original[start:end];matches=list(re.finditer(r"\.INIT\((\d+)'b([01]+)\)",part));assert len(matches)==1;m=matches[0];flipped=''.join('1' if c=='0' else '0' for c in m[2]);mut=part[:m.start(2)]+flipped+part[m.end(2):];vp=out/f'wrong-lut-{i}.v';vp.write_text(original[:start]+mut+original[end:]);ys=out/f'wrong-lut-{i}.ys';ys.write_text(f'read_verilog {lib} {vp}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -prove same 1 -verify\n');log=out/f'wrong-lut-{i}.log'
 with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
 assert rc!=0 and 'proof did fail' in log.read_text();paths += [vp,ys,log];results.append(dict(gate=i,actual_wrong_lut_rejected=True))
(out/'manifest.json').write_text(json.dumps(dict(passed=True,checks=results,sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print('PASS two corrupted actual carry-local LUTs rejected by the combined primitive miter')
