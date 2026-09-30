"""Reject incorrect actual primitive implementations of the bank4 row-hit edits."""
import argparse,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();patch=json.loads(a.patch.read_text());assert patch['passed'];out=a.out.resolve();assert not out.exists();proof=patch['row_proof']
for n,h in proof['sha256'].items():assert digest(n)==h,n
v=Path(proof['miter']);original=v.read_text();isflag=patch['kind']=='packed_same_edge_bank4_row_hit_flag';module='next_predicate' if isflag else 'gate';start=original.index('module '+module);end=original.index('endmodule',start);part=original[start:end];matches=list(re.finditer(r"\.INIT\((\d+)'b([01]+)\)",part));assert len(matches)==(19 if isflag else 6)
cases={}
for i in [0,len(matches)-1]:
 m=matches[i];flipped=''.join('1' if c=='0' else '0' for c in m[2]);mut=part[:m.start(2)]+flipped+part[m.end(2):];cases['wrong_lut_'+str(i)]=original[:start]+mut+original[end:]
if isflag:
 cases['wrong_flag_init']=original.replace("FDRE #(.INIT(1'b0)) f", "FDRE #(.INIT(1'b1)) f")
 cases['ignored_flag_reset']=original.replace('.R(n138431),.CE(1\'b1),.D(fd)', '.R(1\'b0),.CE(1\'b1),.D(fd)')
 for n,t in cases.items():assert t!=original,n
out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';paths=[a.patch,v,Path(__file__),tool,lib];results=[]
for name,text in cases.items():
 vp=out/(name+'.v');vp.write_text(text);ys=out/(name+'.ys');ys.write_text(f'read_verilog {lib} {vp}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat '+('-seq 4 ' if isflag else '')+'-prove same 1 -verify\n');log=out/(name+'.log')
 with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
 assert rc!=0 and 'proof did fail' in log.read_text(),name;paths += [vp,ys,log];results.append(dict(name=name,rejected=True))
(out/'negative-checks.json').write_text(json.dumps(dict(passed=True,actual_primitive_negative_controls=results,sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print(json.dumps(dict(passed=True,negative_controls=len(results))))
