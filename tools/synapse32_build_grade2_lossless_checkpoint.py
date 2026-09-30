#!/usr/bin/env python3
"""Compose stock timing, post-route observation, lossless pip IDs and opt-in pin labels."""
import argparse,difflib,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists()
base=Path('/tmp/tiny3tpu-nextpnr-post-route-checkpoint').resolve();bp=base/'build-manifest.json';parent=json.loads(bp.read_text());assert parent['passed'] and parent['baseline_unchanged']
for n,h in parent['baseline_sha256'].items():assert digest(n)==h,n
assert digest(base/'nextpnr-xilinx')==parent['tool_sha256'] and digest(base/'arch.cc')==parent['source_sha256'] and digest(base/'arch.o')==parent['object_sha256']
root=Path(__file__).resolve().parents[1];fragment=root/'hardware/synapse32/experiments/routing-import/get_pip_unique.inc'
original=(base/'arch.cc').read_text();start=original.index('PipId Arch::getPipByName(IdString name) const');end=original.index('IdString Arch::getPipName(PipId pip) const',start);old=original[start:end];new=fragment.read_text()+'\n'
wire_old='    wire_by_name_cache[name] = ret;';wire_new='    if (ret != WireId() && ret.tile != -1)\n        ret = canonicalWireId(chip_info, ret.tile, ret.index);\n'+wire_old;assert original.count(wire_old)==1
start=original.index('IdString Arch::getPipName(PipId pip) const');end=original.index('void Arch::setup_pip_blacklist()',start);emit_old=original[start:end];brace=emit_old.index('{');emit_new=emit_old[:brace+1]+'\n    auto original_name = [&]() -> IdString {'+emit_old[brace+1:emit_old.rfind('}')]+'    };\n    return id(original_name().str(this) + "@ID=" + std::to_string(pip.tile) + ":" + std::to_string(pip.index));\n}\n\n'
candidate=original.replace(old,new).replace(wire_old,wire_new).replace(emit_old,emit_new);assert candidate.replace(new,old).replace(wire_new,wire_old).replace(emit_new,emit_old)==original
pin=Path('/tmp/tiny3tpu-nextpnr-pinmap-preservation').resolve();pinbuild=pin/'build-manifest.json';pr=json.loads(pinbuild.read_text());assert pr['passed'] and pr['baseline_unchanged']
for n,h in pr['baseline_sha256'].items():assert digest(n)==h,n
assert digest(pin/'arch_place.o')==pr['object_sha256']
out.mkdir();(out/'arch.cc').write_text(candidate);(out/'arch.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='post-route/arch.cc',tofile='lossless/arch.cc')))
compile_cmd=parent['compile'].copy();link_cmd=parent['link'].copy()
for i,v in enumerate(compile_cmd):
 if v.startswith('/') and Path(v).resolve()==base/'arch.cc':compile_cmd[i]=str(out/'arch.cc')
 elif v.startswith('/') and Path(v).resolve()==base/'arch.o':compile_cmd[i]=str(out/'arch.o')
 elif v.startswith('/') and Path(v).resolve()==base/'arch.o.d':compile_cmd[i]=str(out/'arch.o.d')
assert str(out/'arch.cc') in compile_cmd and str(out/'arch.o') in compile_cmd
replaced=0
for i,v in enumerate(link_cmd):
 if v.startswith('/') and Path(v).resolve()==base/'arch.o':link_cmd[i]=str(out/'arch.o')
 elif v.endswith('/xilinx/arch_place.cc.o'):link_cmd[i]=str(pin/'arch_place.o');replaced+=1
assert replaced==1
link_cmd[link_cmd.index('-o')+1]=str(out/'nextpnr-xilinx')
paths=[bp,base/'arch.cc',base/'arch.o',base/'nextpnr-xilinx',pinbuild,pin/'arch_place.o',fragment,Path(__file__).resolve()];hashes=dict(parent['baseline_sha256']);hashes.update({str(q):digest(q) for q in paths})
record=dict(passed=False,scope='Exact pip serialization and canonical wire import, optional post-route observation, and previously verified opt-in pin-label preservation. No changes to timing, placement, routing algorithms or legality. Require normalized exact complete replay before using saved routes.',compile=compile_cmd,link=link_cmd,baseline_sha256=hashes,source_sha256=digest(out/'arch.cc'),patch_sha256=digest(out/'arch.patch'),full_soc_timing_accepted=False)
manifest=out/'build-manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
for label,cmd in [('compile',compile_cmd),('link',link_cmd)]:
 with (out/(label+'.log')).open('w') as log:subprocess.run(cmd,cwd='/tmp/tiny3tpu-nextpnr-current/build',stdout=log,stderr=subprocess.STDOUT,check=True)
record.update(passed=True,baseline_unchanged=all(digest(n)==h for n,h in hashes.items()),object_sha256=digest(out/'arch.o'),tool_sha256=digest(out/'nextpnr-xilinx'));assert record['baseline_unchanged'];manifest.write_text(json.dumps(record,indent=2)+'\n');print('PASS isolated lossless stock-column checkpoint backend build')
