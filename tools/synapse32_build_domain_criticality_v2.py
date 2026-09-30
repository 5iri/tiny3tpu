#!/usr/bin/env python3
"""Build an isolated optional multi-domain criticality aggregation fix."""
import argparse,copy,difflib,hashlib,importlib.util,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(exist_ok=False);root=Path(__file__).resolve().parents[1];parent=Path('/tmp/tiny3tpu-nextpnr-cpu-preg-guidance').resolve();base=Path('/tmp/tiny3tpu-nextpnr-current/build').resolve();bp=parent/'build-manifest.json';record=json.loads(bp.read_text());assert record['passed'];digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for n,h in record['baseline_sha256'].items():assert digest(n)==h
assert digest(parent/'nextpnr-xilinx')==record['tool_sha256']
here=root/'hardware/synapse32/experiments/carry-guidance';helper=here/'domain_criticality_patch.py';spec=importlib.util.spec_from_file_location('patcher',helper);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
for name in ['arch.cc','arch.o','arch.patch','carry_support.h']:(out/name).write_bytes((parent/name).read_bytes())
header=out/'domain_criticality.h';header.write_bytes((here/header.name).read_bytes());original=(parent/'timing.cc').read_text();candidate=mod.patch(original,header);(out/'timing.cc').write_text(candidate);(out/'timing.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='cpu-preg/timing.cc',tofile='domain-criticality/timing.cc')))
compile=[x.replace(str(parent/'timing.cc'),str(out/'timing.cc')).replace(str(parent/'timing.o'),str(out/'timing.o')) for x in record['timing_compile']]
link=[x.replace(str(parent/'arch.o'),str(out/'arch.o')).replace(str(parent/'timing.o'),str(out/'timing.o')).replace(str(parent/'nextpnr-xilinx'),str(out/'nextpnr-xilinx')) for x in record['link']]
inputs=[bp,parent/'timing.cc',parent/'timing.o',parent/'arch.o',parent/'nextpnr-xilinx',helper,here/'domain_criticality.h',here/'test_domain_criticality.cpp',Path(__file__).resolve()]
hashes=copy.deepcopy(record['baseline_sha256']);hashes.update({str(q):digest(q) for q in inputs});test=['clang++','-std=c++17','-O2',str(here/'test_domain_criticality.cpp'),'-o',str(out/'test_domain_criticality')]
record.update(passed=False,scope='Opt-in aggregation of minimum slack and maximum per-domain criticality. Same intra-clock normalization and all path budgets/models remain unchanged. Disabled behavior must replay byte-exactly; no timing acceptance is inferred.',baseline_sha256=hashes,timing_compile=compile,link=link,domain_test_compile=test,timing_source_sha256=digest(out/'timing.cc'),timing_patch_sha256=digest(out/'timing.patch'),domain_header_sha256=digest(header))
manifest=out/'build-manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
for name,command in [('domain-test-compile',test),('domain-test',[str(out/'test_domain_criticality')]),('timing-compile',compile),('link',link)]:
 with (out/(name+'.log')).open('w') as log:subprocess.run(command,cwd=base,stdout=log,stderr=subprocess.STDOUT,check=True)
record.update(baseline_unchanged=all(digest(n)==h for n,h in hashes.items()),timing_object_sha256=digest(out/'timing.o'),tool_sha256=digest(out/'nextpnr-xilinx'),domain_test_log_sha256=digest(out/'domain-test.log'),domain_test_binary_sha256=digest(out/'test_domain_criticality'))
record['passed']=record['baseline_unchanged'];manifest.write_text(json.dumps(record,indent=2)+'\n');print('PASS optional domain criticality build and aggregation regression tests')
