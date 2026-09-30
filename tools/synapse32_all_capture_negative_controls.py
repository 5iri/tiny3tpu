"""Check actual candidate LUT corruptions, constants and dead-cone observers fail closed."""
import argparse,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_ddr_all_capture_encoding import spec
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--parent-input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());out=a.out.resolve();out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';paths=[a.patch,a.parent_input,Path(__file__),Path(__file__).with_name('synapse32_packed_ddr_all_capture_encoding.py'),tool,lib];records=[]
for i,proof in enumerate(patch['shared_capture_proofs']):
 for n,h in proof['sha256'].items():assert digest(n)==h,n
 source=Path(proof['miter']);text=source.read_text();head,candidate=text.split('module candidate',1);matches=list(re.finditer(r"\.INIT\((\d+)'b([01]+)\)",candidate));assert matches;hit=matches[-1];old=hit.group(2);new=old[:-1]+str(1-int(old[-1]));corrupt=head+'module candidate'+candidate[:hit.start(2)]+new+candidate[hit.end(2):];cases={'wrong_lut_'+str(i):corrupt}
 if i<14:
  assert "gold g({1'b0,x},a)" in text;cases['wrong_ground_'+str(i)]=text.replace("gold g({1'b0,x},a)","gold g({1'b1,x},a)")
 for name,bad in cases.items():
  v=out/(name+'.v');v.write_text(bad);ys=out/(name+'.ys');ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/(name+'.log')
  with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
  assert rc!=0 and 'proof did fail' in log.read_text(),name;records.append(dict(name=name,rejected=True));paths.extend([source,v,ys,log])
m=json.loads(a.parent_input.read_text())['modules']['top'];s=spec(m);n=next(iter(s['removed']));cell=m['cells'][n];bit=next(b for p,bs in cell['connections'].items() if cell['port_directions'][p]=='output' for b in bs);ff=next(n for n,c in m['cells'].items() if c['type']=='SLICE_FFX');old=m['cells'][ff]['connections']['D'];m['cells'][ff]['connections']['D']=[bit]
try:spec(m)
except AssertionError:records.append(dict(name='register_observer',rejected=True))
else:raise AssertionError('accepted register observer')
m['cells'][ff]['connections']['D']=old;m['ports']['negative_observer']=dict(direction='output',bits=[bit])
try:spec(m)
except AssertionError:records.append(dict(name='top_observer',rejected=True))
else:raise AssertionError('accepted top observer')
del m['ports']['negative_observer'];typ=cell['type'];cell['type']='SLICE_FFX'
try:spec(m)
except AssertionError:records.append(dict(name='state_deletion',rejected=True))
else:raise AssertionError('accepted state deletion')
cell['type']=typ;assert spec(m)==s;(out/'negative-checks.json').write_text(json.dumps(dict(passed=True,corruptions_rejected=records,sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print(json.dumps(records))
