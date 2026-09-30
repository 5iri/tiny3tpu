#!/usr/bin/env python3
"""Build an isolated router-only variant using unchanged baseline link objects."""
import argparse,difflib,hashlib,json,shlex,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
base=Path('/tmp/tiny3tpu-nextpnr-current');build=base/'build';out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=base/'common/router2.cc';original=source.read_text();marker='        for (auto i : t.route_arcs) {';assert original.count(marker)==1
addition='''        // Give critical sinks first choice of the routing tree. This only
        // permutes pending arc indices; routing legality and timing are unchanged.
        if (timing_driven) {
            const auto &arcs = nets.at(net->udata).arcs;
            std::stable_sort(t.route_arcs.begin(), t.route_arcs.end(),
                             [&](auto a, auto b) { return arcs.at(a).arc_crit > arcs.at(b).arc_crit; });
        }
'''
candidate=original.replace(marker,addition+marker);(out/'router2.cc').write_text(candidate)
(out/'router2.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/router2.cc',tofile='critical-sinks/router2.cc')))
obj='CMakeFiles/nextpnr-xilinx.dir/common/router2.cc.o'
commands=lambda target:subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True).splitlines()[-1]
compile_args=shlex.split(commands(obj));assert str(source) in compile_args
compile_args=[str(out/'router2.cc') if x==str(source) else str(out/'router2.o') if x==obj else str(out/'router2.o.d') if x==obj+'.d' else x for x in compile_args]
link_parts=shlex.split(commands('nextpnr-xilinx'));assert link_parts[:2]==[':','&&'] and link_parts[-2:]==['&&',':'];link_args=link_parts[2:-2]
assert link_args.count(obj)==1
original_inputs=[build/x for x in link_args if x.endswith('.o')]+[Path(x) for x in link_args if x.endswith('.dylib')]
original_inputs += [source,build/'nextpnr-xilinx',Path(__file__).resolve()]
hashes={str(p):digest(p) for p in original_inputs}
link_args=[str(out/'router2.o') if x==obj else x for x in link_args];link_args[link_args.index('-o')+1]=str(out/'nextpnr-xilinx')
record={'scope':'Only common/router2.cc changes: stable sort pending sinks by timing criticality. All other linked objects, including timing and architecture code, are byte-identical baseline objects. No skip/force/constraint changes.','compile':compile_args,'link':link_args,'baseline_sha256':hashes,'source_sha256':digest(out/'router2.cc'),'patch_sha256':digest(out/'router2.patch'),'passed':False}
(out/'build-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
with (out/'compile.log').open('w') as log:rc=subprocess.run(compile_args,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
if rc:raise SystemExit('Compile failed; inspect '+str(out/'compile.log'))
with (out/'link.log').open('w') as log:rc=subprocess.run(link_args,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
if rc:raise SystemExit('Link failed; inspect '+str(out/'link.log'))
record['baseline_unchanged']=all(digest(n)==s for n,s in hashes.items())
record['tool_sha256']=digest(out/'nextpnr-xilinx');record['object_sha256']=digest(out/'router2.o')
version=subprocess.run([str(out/'nextpnr-xilinx'),'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
record['version']=version.stdout;record['passed']=record['baseline_unchanged'] and version.returncode==0
(out/'build-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
if not record['passed']:raise SystemExit('Router build verification failed')
print('PASS isolated critical-sink router build; baseline objects/tool unchanged',record['tool_sha256'])
