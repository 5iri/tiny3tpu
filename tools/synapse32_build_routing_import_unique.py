#!/usr/bin/env python3
"""Build isolated lossless routing-name reader and writer."""
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
experiment=root/'hardware/synapse32/experiments/routing-import'
source=base/'xilinx/arch.cc';original=source.read_text()
start=original.index('PipId Arch::getPipByName(IdString name) const')
end=original.index('IdString Arch::getPipName(PipId pip) const',start)
old=original[start:end];new=(experiment/'get_pip_unique.inc').read_text()+'\n'
wire_old='    wire_by_name_cache[name] = ret;'
wire_new='    if (ret != WireId() && ret.tile != -1)\n        ret = canonicalWireId(chip_info, ret.tile, ret.index);\n'+wire_old
assert original.count(wire_old)==1
emit_start=original.index('IdString Arch::getPipName(PipId pip) const')
emit_end=original.index('void Arch::setup_pip_blacklist()',emit_start)
emit_old=original[emit_start:emit_end]
brace=emit_old.index('{')
emit_new=emit_old[:brace+1]+'\n    auto original_name = [&]() -> IdString {'+emit_old[brace+1:emit_old.rfind('}')]+'    };\n    return id(original_name().str(this) + "@ID=" + std::to_string(pip.tile) + ":" + std::to_string(pip.index));\n}\n\n'
candidate=original.replace(old,new).replace(wire_old,wire_new).replace(emit_old,emit_new)
assert candidate.replace(new,old).replace(wire_new,wire_old).replace(emit_new,emit_old)==original
(out/'arch.cc').write_text(candidate)
(out/'arch.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/arch.cc',tofile='routing-import/arch.cc')))
obj='CMakeFiles/nextpnr-xilinx.dir/xilinx/arch.cc.o'
commands=lambda target:subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True).splitlines()[-1]
compile_args=shlex.split(commands(obj));assert str(source) in compile_args
compile_args=[str(out/'arch.cc') if x==str(source) else str(out/'arch.o') if x==obj else str(out/'arch.o.d') if x==obj+'.d' else x for x in compile_args]
link_parts=shlex.split(commands('nextpnr-xilinx'));assert link_parts[:2]==[':','&&'] and link_parts[-2:]==['&&',':'];link_args=link_parts[2:-2]
timing_obj='CMakeFiles/nextpnr-xilinx.dir/common/timing.cc.o'
assert link_args.count(obj)==link_args.count(timing_obj)==1
inputs=[build/x for x in link_args if x.endswith('.o')]+[Path(x) for x in link_args if x.endswith('.dylib')]
inputs += [source,build/'nextpnr-xilinx',observer/'nextpnr-xilinx',observer/'timing.o',observer/'build-manifest.json',Path(__file__).resolve(),experiment/'get_pip_unique.inc']
hashes={str(q):digest(q) for q in inputs}
link_args=[str(out/'arch.o') if x==obj else str(observer/'timing.o') if x==timing_obj else x for x in link_args]
link_args[link_args.index('-o')+1]=str(out/'nextpnr-xilinx')
record=dict(scope='Only routing serialization changes. Every exported pip includes its exact chipdb tile/index with validated human-readable name; wires are canonicalized. Timing, placement, routing algorithms, chip database and legality checks are unchanged.',compile=compile_args,link=link_args,baseline_sha256=hashes,source_sha256=digest(out/'arch.cc'),patch_sha256=digest(out/'arch.patch'),passed=False)
manifest=out/'build-manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
for name,command in [('compile',compile_args),('link',link_args)]:
    with (out/(name+'.log')).open('w') as log:rc=subprocess.run(command,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
    if rc:raise SystemExit('Failed '+name+': '+str(out/(name+'.log')))
record['baseline_unchanged']=all(digest(n)==h for n,h in hashes.items())
record['tool_sha256']=digest(out/'nextpnr-xilinx');record['object_sha256']=digest(out/'arch.o')
v=subprocess.run([str(out/'nextpnr-xilinx'),'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
record['version']=v.stdout;record['passed']=record['baseline_unchanged'] and v.returncode==0
manifest.write_text(json.dumps(record,indent=2)+'\n');assert record['passed']
print('PASS isolated routing-name import repair; baseline source/objects/tool untouched')
