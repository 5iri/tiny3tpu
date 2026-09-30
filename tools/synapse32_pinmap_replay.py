#!/usr/bin/env python3
"""Replay a routed control and verify optional pin-label preservation changes only labels."""
import argparse,copy,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_timing_report import summarize
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--enabled',action='store_true');a=p.parse_args();reference=a.reference.resolve();out=a.out.resolve();assert not out.exists()
tool=Path('/tmp/tiny3tpu-nextpnr-pinmap-preservation/nextpnr-xilinx').resolve();bp=tool.with_name('build-manifest.json');build=json.loads(bp.read_text());assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
for n,h in build['baseline_sha256'].items():assert digest(n)==h,n
rp=reference/'manifest.json';parent=json.loads(rp.read_text());assert parent['inputs_unchanged'] and parent['timing']['completed']
assert parent.get('clock_constraints_applied',True) and parent.get('requested_placement_exact',True)
for key in ['sha256','output_sha256']:
 for n,h in parent[key].items():assert digest(n)==h,n
base=parent if 'grade_selection' in parent else json.loads(Path(parent['parent']).read_text())
assert base['grade_selection'] and base['domain_criticality_enabled']
command=parent['command'].copy();command[0]=str(tool)
for flag,name in [('--write','routed.json'),('--report','report.json'),('--log','route.log')]:command[command.index(flag)+1]=str(out/name)
assert not any(x in command for x in ['--force','--timing-allow-fail','--ignore-loops','--fasm'])
hashes=dict(parent['sha256']);hashes.update({str(q):digest(q) for q in [rp,tool,bp,reference/'routed.json',reference/'guidance-timing-graph.tsv',Path(__file__).resolve()]})
out.mkdir();record=dict(passed=False,parent=str(rp),enabled=a.enabled,command=command,sha256=hashes,scope='Actual full reroute control: disabled requires exact routed JSON and timing graph; enabled permits only recovered X_ORIG_PORT attributes on connected unchanged pins. No timing or functional acceptance is inferred from metadata repair.',full_soc_timing_accepted=False)
manifest=out/'manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))};env.update(TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'),TINY3TPU_CARRY_GUIDANCE_PS=str(base['symbolic_carry_guidance_ps']),TINY3TPU_PRIMITIVE_GUIDANCE='1',TINY3TPU_DOMAIN_CRITICALITY='1',NEXTPNR_PLACER_BETA=str(base['placement_beta']))
if a.enabled:env['TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS']='1'
with (out/'console.log').open('w') as f:rc=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
record.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in hashes.items()),timing=summarize((out/'route.log').read_text(),exit_code=rc))
gold=json.loads((reference/'routed.json').read_text());actual=json.loads((out/'routed.json').read_text());restored=copy.deepcopy(actual);changes=[]
assert set(gold['modules'])==set(actual['modules'])
for mn,m in gold['modules'].items():
 assert set(m['cells'])==set(actual['modules'][mn]['cells'])
 for n,c in m['cells'].items():
  ac=actual['modules'][mn]['cells'][n];old=c['attributes'];new=ac['attributes']
  assert all(new.get(k)==v for k,v in old.items()),n
  for k in new.keys()-old.keys():
   assert a.enabled and k.startswith('X_ORIG_PORT_') and c['type']=='SLICE_LUTX',(n,k)
   port=k[len('X_ORIG_PORT_'):];assert c['connections'].get(port)==ac['connections'].get(port) and c['connections'].get(port)
   changes.append(dict(cell=n,physical_port=port,logical_port=new[k]));del restored['modules'][mn]['cells'][n]['attributes'][k]
record['only_logical_labels_changed']=restored==gold
record['routed_json_exact']=actual==gold
record['restored_labels']=changes
record['timing_graph_exact']=digest(out/'guidance-timing-graph.tsv')==digest(reference/'guidance-timing-graph.tsv')
record['native_fmax_exact']={k:(v['mhz'],v['target_mhz'],v['status']) for k,v in record['timing']['final_clocks'].items()}=={k:(v['mhz'],v['target_mhz'],v['status']) for k,v in parent['timing']['final_clocks'].items()}
record['passed']=rc==0 and record['inputs_unchanged'] and record['only_logical_labels_changed'] and record['native_fmax_exact'] and (bool(changes) if a.enabled else record['routed_json_exact'] and record['timing_graph_exact'])
record['output_sha256']={str(out/n):digest(out/n) for n in ['routed.json','guidance-timing-graph.tsv','route.log','report.json']}
manifest.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record[k] for k in ['passed','enabled','only_logical_labels_changed','native_fmax_exact','timing_graph_exact']}));assert record['passed'],manifest
