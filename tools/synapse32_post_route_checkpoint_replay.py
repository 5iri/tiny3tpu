#!/usr/bin/env python3
"""Require exact full-route replay while exporting a pre-fixup placement."""
import argparse,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_timing_report import summarize
p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();reference=a.reference.resolve();out=a.out.resolve();assert not out.exists()
tool=Path('/tmp/tiny3tpu-nextpnr-post-route-checkpoint/nextpnr-xilinx').resolve();bp=tool.with_name('build-manifest.json');build=json.loads(bp.read_text());assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
for n,h in build['baseline_sha256'].items():assert digest(n)==h
rp=reference/'manifest.json';parent=json.loads(rp.read_text());assert parent['inputs_unchanged'] and parent['timing']['completed'] and parent['grade_selection'] and parent['domain_criticality_enabled']
for key in ['sha256','output_sha256']:
 for n,h in parent[key].items():assert digest(n)==h
command=parent['command'].copy();command[0]=str(tool)
for flag,name in [('--write','routed.json'),('--report','report.json'),('--log','route.log')]:command[command.index(flag)+1]=str(out/name)
assert not any(x in command for x in ['--no-pack','--no-place','--force','--timing-allow-fail','--ignore-loops','--fasm'])
hashes=dict(parent['sha256']);hashes.update({str(q):digest(q) for q in [rp,tool,bp,reference/'routed.json',reference/'guidance-timing-graph.tsv',Path(__file__).resolve()]})
out.mkdir();record=dict(passed=False,parent=str(rp),command=command,sha256=hashes,scope='Optional post-route, pre-pin-fixup observation only. Require exact complete routed JSON, native clock results and native guidance graph, not only equal placements.',full_soc_timing_accepted=False)
manifest=out/'manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))};env.update(TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'),TINY3TPU_CARRY_GUIDANCE_PS=str(parent['symbolic_carry_guidance_ps']),TINY3TPU_PRIMITIVE_GUIDANCE='1',TINY3TPU_DOMAIN_CRITICALITY='1',NEXTPNR_PLACER_BETA=str(parent['placement_beta']),TINY3TPU_POST_ROUTE_CHECKPOINT=str(out/'pre-fixup.json'))
with (out/'console.log').open('w') as f:rc=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
record.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in hashes.items()),timing=summarize((out/'route.log').read_text(),exit_code=rc))
record['routed_json_exact']=rc==0 and json.loads((out/'routed.json').read_text())==json.loads((reference/'routed.json').read_text())
record['timing_graph_exact']=rc==0 and digest(out/'guidance-timing-graph.tsv')==digest(reference/'guidance-timing-graph.tsv')
record['native_fmax_exact']={k:(v['mhz'],v['target_mhz'],v['status']) for k,v in record['timing']['final_clocks'].items()}=={k:(v['mhz'],v['target_mhz'],v['status']) for k,v in parent['timing']['final_clocks'].items()}
record['checkpoint_exists']=(out/'pre-fixup.json').exists()
checkpoint_design=json.loads((out/'pre-fixup.json').read_text())
record['routed_net_records']=sum(bool(v.get('attributes',{}).get('ROUTING','').strip()) for v in checkpoint_design['modules']['top']['netnames'].values())
assert record['routed_net_records']>40000
record['passed']=rc==0 and all(record[k] for k in ['inputs_unchanged','routed_json_exact','timing_graph_exact','native_fmax_exact','checkpoint_exists'])
record['output_sha256']={str(q):digest(q) for q in [out/n for n in ['routed.json','guidance-timing-graph.tsv','pre-fixup.json','route.log','report.json']] if q.exists()}
manifest.write_text(json.dumps(record,indent=2)+'\n');assert record['passed'],manifest
print('PASS stock-column checkpoint export: exact routed JSON, native graph and Fmax replay')
