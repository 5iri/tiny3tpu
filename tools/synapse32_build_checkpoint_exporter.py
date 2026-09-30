#!/usr/bin/env python3
"""Build an isolated pre-fixup checkpoint exporter; all original checks remain."""
import argparse,difflib,hashlib,json,shlex,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
base=Path('/tmp/tiny3tpu-nextpnr-current');build=base/'build';out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=base/'xilinx/arch.cc';original=source.read_text();marker='    fixupPlacement();';assert original.count(marker)==1
addition='    // Observe the legal placement before pin/constant legalization changes\n    // the packed representation. Always continue the original flow afterward.\n    if (const char *checkpoint = getenv("TINY3TPU_PRE_FIXUP_CHECKPOINT")) {\n        archInfoToAttributes();\n        std::string filename(checkpoint);\n        std::ofstream f(filename);\n        if (!write_json_file(f, filename, getCtx()))\n            log_error("Failed to write pre-fixup checkpoint.\\n");\n    }\n'
candidate=original.replace('#include "log.h"','#include "log.h"\n#include "jsonwrite.h"').replace(marker,addition+marker)
(out/'arch.cc').write_text(candidate)
(out/'arch.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/arch.cc',tofile='checkpoint/arch.cc')))
obj='CMakeFiles/nextpnr-xilinx.dir/xilinx/arch.cc.o'
commands=lambda target:subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True).splitlines()[-1]
compile_args=shlex.split(commands(obj));assert str(source) in compile_args
compile_args=[str(out/'arch.cc') if x==str(source) else str(out/'arch.o') if x==obj else str(out/'arch.o.d') if x==obj+'.d' else x for x in compile_args]
link_parts=shlex.split(commands('nextpnr-xilinx'));assert link_parts[:2]==[':','&&'] and link_parts[-2:]==['&&',':'];link_args=link_parts[2:-2]
assert link_args.count(obj)==1
original_inputs=[build/x for x in link_args if x.endswith('.o')]+[Path(x) for x in link_args if x.endswith('.dylib')]
original_inputs += [source,build/'nextpnr-xilinx',Path(__file__).resolve()]
hashes={str(p):digest(p) for p in original_inputs}
link_args=[str(out/'arch.o') if x==obj else x for x in link_args];link_args[link_args.index('-o')+1]=str(out/'nextpnr-xilinx')
record={'scope':'Only an optional pre-fixup JSON checkpoint export is added to arch.cc. Original placement, legality, fixup, routing and timing flow continues unchanged. All other link objects are unchanged.','compile':compile_args,'link':link_args,'baseline_sha256':hashes,'source_sha256':digest(out/'arch.cc'),'patch_sha256':digest(out/'arch.patch'),'passed':False}
(out/'build-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
with (out/'compile.log').open('w') as log:rc=subprocess.run(compile_args,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
if rc:raise SystemExit('Compile failed; inspect '+str(out/'compile.log'))
with (out/'link.log').open('w') as log:rc=subprocess.run(link_args,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
if rc:raise SystemExit('Link failed; inspect '+str(out/'link.log'))
record['baseline_unchanged']=all(digest(n)==s for n,s in hashes.items())
record['tool_sha256']=digest(out/'nextpnr-xilinx');record['object_sha256']=digest(out/'arch.o')
version=subprocess.run([str(out/'nextpnr-xilinx'),'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
record['version']=version.stdout;record['passed']=record['baseline_unchanged'] and version.returncode==0
(out/'build-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
if not record['passed']:raise SystemExit('Router build verification failed')
print('PASS isolated checkpoint exporter build; baseline objects/tool unchanged',record['tool_sha256'])
