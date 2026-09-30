#!/usr/bin/env python3
"""Allow uncascaded DSP roots to use either physical slot, behind an opt-in flag."""
import argparse,difflib,json,shlex,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists()
base=Path('/tmp/tiny3tpu-nextpnr-current').resolve();build=base/'build';parent_dir=Path('/tmp/tiny3tpu-nextpnr-grade2-guidance').resolve();parent_path=parent_dir/'build-manifest.json';parent=json.loads(parent_path.read_text());assert parent['passed'] and parent['baseline_unchanged'] and digest(parent_dir/'nextpnr-xilinx')==parent['tool_sha256']
for n,h in parent['baseline_sha256'].items():assert digest(n)==h
source=base/'xilinx/pack_dsp_xc7.cc';original=source.read_text();marker='        walk_dsp(root, root, BEL_UPPER_DSP);';assert original.count(marker)==1
addition='''
        // A standalone DSP has no cascade direction/alignment requirement.
        // Preserve the original lower/upper constraints for every cascade.
        if (std::getenv("TINY3TPU_FREE_STANDALONE_DSP_SLOTS") != nullptr &&
            root->constr_parent == nullptr && root->constr_children.empty()) {
            root->constr_z = root->UNCONSTR;
            root->constr_abs_z = false;
        }
'''
candidate=original.replace('#include <boost/algorithm/string.hpp>','#include <boost/algorithm/string.hpp>\n#include <cstdlib>',1).replace(marker,marker+addition)
assert candidate.replace(addition,'').replace('\n#include <cstdlib>','',1)==original
out.mkdir();(out/'pack_dsp_xc7.cc').write_text(candidate);(out/'pack_dsp.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/pack_dsp_xc7.cc',tofile='free-slots/pack_dsp_xc7.cc')))
obj='CMakeFiles/nextpnr-xilinx.dir/xilinx/pack_dsp_xc7.cc.o';compile_cmd=shlex.split(subprocess.check_output(['ninja','-C',str(build),'-t','commands',obj],text=True).splitlines()[-1]);assert obj in compile_cmd
compile_cmd=[str(out/'pack_dsp.o') if v==obj else str(out/'pack_dsp.o.d') if v==obj+'.d' else str(out/'pack_dsp_xc7.cc') if v.startswith('/') and Path(v).resolve()==source else v for v in compile_cmd]
assert str(out/'pack_dsp_xc7.cc') in compile_cmd
link_cmd=parent['link'].copy();assert obj in link_cmd;link_cmd=[str(out/'pack_dsp.o') if v==obj else v for v in link_cmd];link_cmd[link_cmd.index('-o')+1]=str(out/'nextpnr-xilinx')
paths=[source,build/obj,parent_path,parent_dir/'nextpnr-xilinx',parent_dir/'arch.o',parent_dir/'timing.o',Path(__file__).resolve()];hashes={str(q):digest(q) for q in paths};hashes.update(parent['baseline_sha256'])
record=dict(passed=False,scope='Optional removal of the artificial lower-slot constraint only for standalone DSP roots. Existing cascades, logic, timing models, clocks, routing and legality checks remain unchanged. Exact disabled replay and actual pack/placement tests are required.',compile=compile_cmd,link=link_cmd,baseline_sha256=hashes,source_sha256=digest(out/'pack_dsp_xc7.cc'),patch_sha256=digest(out/'pack_dsp.patch'),full_soc_timing_accepted=False)
manifest=out/'build-manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
for label,cmd in [('compile',compile_cmd),('link',link_cmd)]:
 with (out/(label+'.log')).open('w') as log:subprocess.run(cmd,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
record.update(passed=True,baseline_unchanged=all(digest(n)==h for n,h in hashes.items()),object_sha256=digest(out/'pack_dsp.o'),tool_sha256=digest(out/'nextpnr-xilinx'));assert record['baseline_unchanged'];manifest.write_text(json.dumps(record,indent=2)+'\n');print('PASS isolated standalone-DSP slot build; original backend untouched')
