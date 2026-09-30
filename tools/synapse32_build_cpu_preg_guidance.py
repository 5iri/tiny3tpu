#!/usr/bin/env python3
"""Build isolated carry, boot-RAM and pure registered-multiply timing guidance."""
import argparse,difflib,hashlib,json,shlex,subprocess,importlib.util
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
'''+(experiment/'fallback.inc').read_text()
assert original.count(old)==1
header=out/'carry_support.h';header.write_bytes((experiment/'carry_support.h').read_bytes())
include=f'#include <cstdlib>\n#include "{header}"\n'
class_old='cell->type == id_CARRY4 && cell->bel != BelId()'
class_new='cell->type == id_CARRY4 && (cell->bel != BelId() || std::getenv("TINY3TPU_CARRY_GUIDANCE_PS") != nullptr)'
assert original.count(class_old)==1
candidate=original.replace('#include <algorithm>','#include <algorithm>\n'+include,1).replace(old,new).replace(class_old,class_new)
primitive_path=experiment/'cpu_preg_primitive_timing.inc'
primitive=primitive_path.read_text()
class_insert='    TinyPrimitiveTiming timing;\n    if (tinyPrimitiveTiming(this,cell,port,timing)) {\n        clockInfoCount = timing.clocked ? 1 : 0;\n        return timing.cls;\n    }\n'
clock_insert='    TinyPrimitiveTiming timing;\n    if (tinyPrimitiveTiming(this,cell,port,timing)) {\n        NPNR_ASSERT(timing.clocked && index == 0);\n        TimingClockingInfo info;\n        info.clock_port=id(timing.clock);\n        info.edge=RISING_EDGE;\n        info.setup=getDelayFromNS(timing.setup);\n        info.hold=getDelayFromNS(timing.hold);\n        info.clockToQ=getDelayFromNS(timing.cq);\n        return info;\n    }\n'
class_sig='TimingPortClass Arch::getPortTimingClass(const CellInfo *cell, IdString port, int &clockInfoCount) const\n{\n'
clock_sig='TimingClockingInfo Arch::getPortClockingInfo(const CellInfo *cell, IdString port, int index) const\n{\n'
assert candidate.count(class_sig)==candidate.count(clock_sig)==1
candidate=candidate.replace('IdString Arch::dspStripBusIndex',primitive+'\nIdString Arch::dspStripBusIndex',1).replace(class_sig,class_sig+class_insert).replace(clock_sig,clock_sig+clock_insert)
assert candidate.replace(primitive+'\n','').replace(class_insert,'').replace(clock_insert,'').replace(class_new,class_old).replace(include,'').replace('#include <algorithm>\n\n','#include <algorithm>\n',1).replace(new,old)==original
(out/'arch.cc').write_text(candidate)
(out/'arch.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/arch.cc',tofile='carry-guidance/arch.cc')))
mixed_helper=experiment/'mixed_output_patch.py'
spec=importlib.util.spec_from_file_location('mixed_output_patch',mixed_helper)
mixed_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(mixed_module)
timing_source=observer/'timing.cc';timing_original=timing_source.read_text()
timing_candidate=mixed_module.patch(timing_original)
(out/'timing.cc').write_text(timing_candidate)
(out/'timing.patch').write_text(''.join(difflib.unified_diff(timing_original.splitlines(True),timing_candidate.splitlines(True),fromfile='observer/timing.cc',tofile='mixed/timing.cc')))

obj='CMakeFiles/nextpnr-xilinx.dir/xilinx/arch.cc.o'
commands=lambda target:subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True).splitlines()[-1]
compile_args=shlex.split(commands(obj));assert str(source) in compile_args
compile_args=[str(out/'arch.cc') if x==str(source) else str(out/'arch.o') if x==obj else str(out/'arch.o.d') if x==obj+'.d' else x for x in compile_args]
link_parts=shlex.split(commands('nextpnr-xilinx'));assert link_parts[:2]==[':','&&'] and link_parts[-2:]==['&&',':'];link_args=link_parts[2:-2]
timing_obj='CMakeFiles/nextpnr-xilinx.dir/common/timing.cc.o'
assert link_args.count(obj)==link_args.count(timing_obj)==1
inputs=[build/x for x in link_args if x.endswith('.o')]+[Path(x) for x in link_args if x.endswith('.dylib')]
inputs += [mixed_helper,timing_source,root/'tools/synapse32_lutram_timing_model.py',root/'tools/synapse32_cpu_preg_dsp_model.py',source,build/'nextpnr-xilinx',observer/'nextpnr-xilinx',observer/'timing.o',observer/'build-manifest.json',Path(__file__).resolve(),experiment/'carry_support.h',experiment/'fallback.inc',experiment/'test_support.cpp',primitive_path,root/'build-dsp-preg-timing/ds182.txt',root/'build-dsp-preg-timing/ds182.pdf',root/'build-dsp-preg-timing/limits.json']
hashes={str(q):digest(q) for q in inputs}
link_args=[str(out/'arch.o') if x==obj else str(out/'timing.o') if x==timing_obj else x for x in link_args]
link_args[link_args.index('-o')+1]=str(out/'nextpnr-xilinx')
timing_compile=shlex.split(commands(timing_obj))
assert str(base/'common/timing.cc') in timing_compile
timing_compile=[str(out/'timing.cc') if x==str(base/'common/timing.cc') else str(out/'timing.o') if x==timing_obj else str(out/'timing.o.d') if x==timing_obj+'.d' else x for x in timing_compile]
test_command=['clang++','-std=c++17','-O2',str(experiment/'test_support.cpp'),'-o',str(out/'test_support')]
record=dict(scope='Optional CARRY4 guidance and DS182 boot-RAM/pure MREG multiply timing. Both features disabled by default. These optimization models do not validate physical timing. LUTRAM keeps both read-address and write-clock origins. Unsupported registered DSP profiles abort. No legality or constraint check is relaxed.',compile=compile_args,timing_compile=timing_compile,timing_source_sha256=digest(out/'timing.cc'),timing_patch_sha256=digest(out/'timing.patch'),link=link_args,test_compile=test_command,baseline_sha256=hashes,source_sha256=digest(out/'arch.cc'),patch_sha256=digest(out/'arch.patch'),header_sha256=digest(header),passed=False)
manifest=out/'build-manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
for name,command in [('test-compile',test_command),('test',[str(out/'test_support')]),('compile',compile_args),('timing-compile',timing_compile),('link',link_args)]:
    with (out/(name+'.log')).open('w') as log:rc=subprocess.run(command,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
    if rc:raise SystemExit('Failed '+name+': '+str(out/(name+'.log')))
record['baseline_unchanged']=all(digest(n)==h for n,h in hashes.items())
record['timing_object_sha256']=digest(out/'timing.o')
record['tool_sha256']=digest(out/'nextpnr-xilinx');record['object_sha256']=digest(out/'arch.o')
record['test_log_sha256']=digest(out/'test.log');record['test_binary_sha256']=digest(out/'test_support')
v=subprocess.run([str(out/'nextpnr-xilinx'),'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
record['version']=v.stdout;record['passed']=record['baseline_unchanged'] and v.returncode==0
manifest.write_text(json.dumps(record,indent=2)+'\n');assert record['passed']
print('PASS isolated carry-guidance build; exhaustive support test; baseline untouched')
