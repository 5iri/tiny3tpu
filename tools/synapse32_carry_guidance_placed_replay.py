#!/usr/bin/env python3
"""Require exact routed-design/graph replay with carry guidance disabled."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
from synapse32_timing_report import summarize

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();reference=a.reference.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
tool=Path('/tmp/tiny3tpu-nextpnr-carry-guidance-placed/nextpnr-xilinx');bp=tool.with_name('build-manifest.json');build=json.loads(bp.read_text())
assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
for n,h in build['baseline_sha256'].items():assert digest(n)==h,n
for n,k in [('arch.cc','source_sha256'),('arch.o','object_sha256'),('arch.patch','patch_sha256'),('carry_support.h','header_sha256')]:assert digest(tool.with_name(n))==build[k]
rp=reference/'manifest.json';parent=json.loads(rp.read_text())
assert parent['inputs_unchanged'] and parent['timing']['completed']
for key in ['sha256','output_sha256']:
    for n,h in parent[key].items():assert digest(n)==h,n
command=parent['command'].copy();command[0]=str(tool)
for flag,name in [('--write','routed.json'),('--report','report.json'),('--log','route.log')]:command[command.index(flag)+1]=str(out/name)
assert not any(x in command for x in ['--force','--timing-allow-fail','--ignore-loops'])
inputs=[tool,bp,rp,reference/'routed.json',reference/'timing-graph.tsv',Path(__file__).resolve()]
hashes={str(q):digest(q) for q in inputs};hashes.update(parent['sha256'])
record=dict(command=command,carry_guidance_enabled=False,sha256=hashes,passed=False,full_soc_timing_accepted=False)
manifest=out/'manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))};env['TINY3TPU_TIMING_GRAPH']=str(out/'timing-graph.tsv')
with (out/'console.log').open('w') as log:rc=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
record['timing']=summarize((out/'route.log').read_text(),exit_code=rc)
record['inputs_unchanged']=all(digest(n)==h for n,h in hashes.items())
record['routed_json_exact']=rc==0 and digest(out/'routed.json')==digest(reference/'routed.json')
record['timing_graph_exact']=rc==0 and digest(out/'timing-graph.tsv')==digest(reference/'timing-graph.tsv')
record['native_fmax_exact']={k:v['mhz'] for k,v in record['timing']['final_clocks'].items()}=={k:v['mhz'] for k,v in parent['timing']['final_clocks'].items()}
record['passed']=rc==0 and all(record[k] for k in ['inputs_unchanged','routed_json_exact','timing_graph_exact','native_fmax_exact'])
record['output_sha256']={str(out/n):digest(out/n) for n in ['routed.json','timing-graph.tsv','report.json','route.log'] if (out/n).exists()}
manifest.write_text(json.dumps(record,indent=2)+'\n');assert record['passed'],manifest
print('PASS disabled carry guidance: routed JSON, timing graph and native Fmax exactly reproduce reference')
