#!/usr/bin/env python3
"""Build isolated optional CARRY4 connectivity guidance for the open placer."""
import argparse,difflib,hashlib,json,shlex,subprocess
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];base=Path('/tmp/tiny3tpu-nextpnr-current');build=base/'build'
observer=Path('/tmp/tiny3tpu-nextpnr-timing-graph-observer');out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
parent=json.loads((observer/'build-manifest.json').read_text())
assert parent['passed'] and parent['baseline_unchanged'] and digest(observer/'nextpnr-xilinx')==parent['tool_sha256']
assert digest(observer/'timing.o')==parent['object_sha256']
for n,h in parent['baseline_sha256'].items():assert digest(n)==h,n
experiment=root/'hardware/synapse32/experiments/carry-guidance'
source=base/'xilinx/arch.cc';original=source.read_text()
old='''        if (xc7 && inst_id != -1) {
            return xc7_cell_timing_lookup(tt_id, inst_id, id("CARRY4"), fromPort, toPort, delay);
        }'''
new='''        if (xc7 && inst_id != -1 &&
            xc7_cell_timing_lookup(tt_id, inst_id, id("CARRY4"), fromPort, toPort, delay))
            return true;
'''+(experiment/'fallback.inc').read_text().replace('if (guidance_ps >= 0) {', 'if (guidance_ps >= 0 && cell->bel != BelId()) {')
assert original.count(old)==1
header=out/'carry_support.h';header.write_bytes((experiment/'carry_support.h').read_bytes())
include=f'#include <cstdlib>\n#include "{header}"\n'
candidate=original.replace('#include <algorithm>','#include <algorithm>\n'+include,1).replace(old,new)
assert candidate.replace(include,'').replace('#include <algorithm>\n\n','#include <algorithm>\n',1).replace(new,old)==original
(out/'arch.cc').write_text(candidate)
(out/'arch.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/arch.cc',tofile='carry-guidance/arch.cc')))
obj='CMakeFiles/nextpnr-xilinx.dir/xilinx/arch.cc.o'
commands=lambda target:subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True).splitlines()[-1]
compile_args=shlex.split(commands(obj));assert str(source) in compile_args
compile_args=[str(out/'arch.cc') if x==str(source) else str(out/'arch.o') if x==obj else str(out/'arch.o.d') if x==obj+'.d' else x for x in compile_args]
link_parts=shlex.split(commands('nextpnr-xilinx'));assert link_parts[:2]==[':','&&'] and link_parts[-2:]==['&&',':'];link_args=link_parts[2:-2]
timing_obj='CMakeFiles/nextpnr-xilinx.dir/common/timing.cc.o'
assert link_args.count(obj)==link_args.count(timing_obj)==1
inputs=[build/x for x in link_args if x.endswith('.o')]+[Path(x) for x in link_args if x.endswith('.dylib')]
inputs += [source,build/'nextpnr-xilinx',observer/'nextpnr-xilinx',observer/'timing.o',observer/'build-manifest.json',Path(__file__).resolve(),experiment/'carry_support.h',experiment/'fallback.inc',experiment/'test_support.cpp']
hashes={str(q):digest(q) for q in inputs}
link_args=[str(out/'arch.o') if x==obj else str(observer/'timing.o') if x==timing_obj else x for x in link_args]
link_args[link_args.index('-o')+1]=str(out/'nextpnr-xilinx')
test_command=['clang++','-std=c++17','-O2',str(experiment/'test_support.cpp'),'-o',str(out/'test_support')]
record=dict(scope='Only an optional placed-cell missing-CARRY4 timing fallback changes; this agrees with existing port timing classification. Disabled by default. Symbolic delay is optimization guidance, not validated device timing. No placement/routing legality, packing, netlist or constraint checks are relaxed.',compile=compile_args,link=link_args,test_compile=test_command,baseline_sha256=hashes,source_sha256=digest(out/'arch.cc'),patch_sha256=digest(out/'arch.patch'),header_sha256=digest(header),passed=False)
manifest=out/'build-manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
for name,command in [('test-compile',test_command),('test',[str(out/'test_support')]),('compile',compile_args),('link',link_args)]:
    with (out/(name+'.log')).open('w') as log:rc=subprocess.run(command,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
    if rc:raise SystemExit('Failed '+name+': '+str(out/(name+'.log')))
record['baseline_unchanged']=all(digest(n)==h for n,h in hashes.items())
record['tool_sha256']=digest(out/'nextpnr-xilinx');record['object_sha256']=digest(out/'arch.o')
record['test_log_sha256']=digest(out/'test.log');record['test_binary_sha256']=digest(out/'test_support')
v=subprocess.run([str(out/'nextpnr-xilinx'),'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
record['version']=v.stdout;record['passed']=record['baseline_unchanged'] and v.returncode==0
manifest.write_text(json.dumps(record,indent=2)+'\n');assert record['passed']
print('PASS isolated carry-guidance build; exhaustive support test; baseline untouched')
