#!/usr/bin/env python3
"""Preserve logical labels on untouched pins during routing fixup, opt-in only."""
import argparse,difflib,json,shlex,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists()
base=Path('/tmp/tiny3tpu-nextpnr-current').resolve();build=base/'build';parent_dir=Path('/tmp/tiny3tpu-nextpnr-grade2-guidance').resolve();parent_path=parent_dir/'build-manifest.json';parent=json.loads(parent_path.read_text());assert parent['passed'] and parent['baseline_unchanged'] and digest(parent_dir/'nextpnr-xilinx')==parent['tool_sha256']
for n,h in parent['baseline_sha256'].items():assert digest(n)==h
source=base/'xilinx/arch_place.cc';original=source.read_text()
marker='''            for (int i = 0; i < 6; i++) {
                if (lut6)
                    lut6->attrs.erase(id("X_ORIG_PORT_" + ports[i].str(this)));
'''
assert original.count(marker)==1
addition='''                // Only the permutation's source/destination pins were disconnected.
                // Other pins retain both their net and their logical identity.
                if (getenv("TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS") != nullptr) {
                    bool touched = new_connections.count(ports[i]) != 0;
                    for (const auto &nc : new_connections)
                        for (auto dst : nc.second)
                            touched = touched || dst == ports[i];
                    if (!touched)
                        continue;
                }
'''
candidate=original.replace(marker,marker.replace('                if (lut6)',addition+'                if (lut6)',1))
assert candidate.replace(addition,'')==original
out.mkdir();(out/'arch_place.cc').write_text(candidate);(out/'pinmap.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/arch_place.cc',tofile='pinmap/arch_place.cc')))
obj='CMakeFiles/nextpnr-xilinx.dir/xilinx/arch_place.cc.o';compile_cmd=shlex.split(subprocess.check_output(['ninja','-C',str(build),'-t','commands',obj],text=True).splitlines()[-1]);assert obj in compile_cmd
compile_cmd=[str(out/'arch_place.o') if v==obj else str(out/'arch_place.o.d') if v==obj+'.d' else str(out/'arch_place.cc') if v.startswith('/') and Path(v).resolve()==source else v for v in compile_cmd]
assert str(out/'arch_place.cc') in compile_cmd
link_cmd=parent['link'].copy();assert obj in link_cmd;link_cmd=[str(out/'arch_place.o') if v==obj else v for v in link_cmd];link_cmd[link_cmd.index('-o')+1]=str(out/'nextpnr-xilinx')
paths=[source,build/obj,parent_path,parent_dir/'nextpnr-xilinx',parent_dir/'arch.o',parent_dir/'timing.o',Path(__file__).resolve()];hashes={str(q):digest(q) for q in paths};hashes.update(parent['baseline_sha256'])
record=dict(passed=False,scope='Opt-in preservation of logical pin labels only on pins untouched by routing permutation. Connections, placement, routing and delay tables unchanged. Require disabled replay and enabled metadata-only comparisons before use.',compile=compile_cmd,link=link_cmd,baseline_sha256=hashes,source_sha256=digest(out/'arch_place.cc'),patch_sha256=digest(out/'pinmap.patch'),full_soc_timing_accepted=False)
manifest=out/'build-manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
for label,cmd in [('compile',compile_cmd),('link',link_cmd)]:
 with (out/(label+'.log')).open('w') as log:subprocess.run(cmd,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
record.update(passed=True,baseline_unchanged=all(digest(n)==h for n,h in hashes.items()),object_sha256=digest(out/'arch_place.o'),tool_sha256=digest(out/'nextpnr-xilinx'));assert record['baseline_unchanged'];manifest.write_text(json.dumps(record,indent=2)+'\n');print('PASS isolated untouched-pin label preservation build; original backend unchanged')
