#!/usr/bin/env python3
"""Add optional checkpoint export to the verified stock-column backend."""
import argparse,difflib,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists()
base=Path('/tmp/tiny3tpu-nextpnr-grade2-guidance').resolve();build_path=base/'build-manifest.json';parent=json.loads(build_path.read_text());assert parent['passed'] and parent['baseline_unchanged']
for n,h in parent['baseline_sha256'].items():assert digest(n)==h
assert digest(base/'nextpnr-xilinx')==parent['tool_sha256'] and digest(base/'arch.cc')==parent['source_sha256'] and digest(base/'arch.o')==parent['object_sha256']
original=(base/'arch.cc').read_text();marker='    fixupRouting();';assert original.count(marker)==1
addition='''    // Optional observation after routing, before packed-pin legalization; continue unchanged.
    if (const char *checkpoint = getenv("TINY3TPU_POST_ROUTE_CHECKPOINT")) {
        archInfoToAttributes();
        std::string filename(checkpoint);
        std::ofstream f(filename);
        if (!write_json_file(f, filename, getCtx()))
            log_error("Failed to write post-route pre-pin-fixup checkpoint.\\n");
    }
'''
include='#include "jsonwrite.h"\n';assert include not in original
candidate=original.replace('#include "log.h"','#include "log.h"\n'+include,1).replace(marker,addition+marker)
assert candidate.replace(addition,'').replace('#include "log.h"\n'+include,'#include "log.h"',1)==original
out.mkdir();(out/'arch.cc').write_text(candidate);(out/'arch.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='grade2/arch.cc',tofile='checkpoint/arch.cc')))
compile_cmd=parent['compile'].copy();link_cmd=parent['link'].copy()
for i,v in enumerate(compile_cmd):
 if v.startswith('/') and Path(v).resolve()==base/'arch.cc':compile_cmd[i]=str(out/'arch.cc')
 elif v.startswith('/') and Path(v).resolve()==base/'arch.o':compile_cmd[i]=str(out/'arch.o')
 elif v.startswith('/') and Path(v).resolve()==base/'arch.o.d':compile_cmd[i]=str(out/'arch.o.d')
assert str(out/'arch.cc') in compile_cmd and str(out/'arch.o') in compile_cmd
for i,v in enumerate(link_cmd):
 if v.startswith('/') and Path(v).resolve()==base/'arch.o':link_cmd[i]=str(out/'arch.o')
link_cmd[link_cmd.index('-o')+1]=str(out/'nextpnr-xilinx');assert str(out/'arch.o') in link_cmd
paths=[build_path,base/'arch.cc',base/'arch.o',base/'nextpnr-xilinx',base/'timing.o',base/'carry_support.h',base/'domain_criticality.h',Path(__file__).resolve()]
hashes={str(q):digest(q) for q in paths};hashes.update(parent['baseline_sha256'])
record=dict(passed=False,scope='Only an optional post-route pre-pin-fixup JSON export is added. Timing, placement, routing and legality algorithms are unchanged. Exact enabled replay is required before using checkpoints.',compile=compile_cmd,link=link_cmd,baseline_sha256=hashes,source_sha256=digest(out/'arch.cc'),patch_sha256=digest(out/'arch.patch'),full_soc_timing_accepted=False)
manifest=out/'build-manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
for label,cmd in [('compile',compile_cmd),('link',link_cmd)]:
 with (out/(label+'.log')).open('w') as log:subprocess.run(cmd,cwd='/tmp/tiny3tpu-nextpnr-current/build',stdout=log,stderr=subprocess.STDOUT,check=True)
record.update(passed=True,baseline_unchanged=all(digest(n)==h for n,h in hashes.items()),object_sha256=digest(out/'arch.o'),tool_sha256=digest(out/'nextpnr-xilinx'));assert record['baseline_unchanged'];manifest.write_text(json.dumps(record,indent=2)+'\n');print('PASS isolated stock-column checkpoint exporter build; original backend unchanged')
