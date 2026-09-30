"""Bind the incremental route, equivalence, tool build and expanded diagnostic results."""
import json
from pathlib import Path
from synapse32_apply_bram_timing import digest
root=Path(__file__).resolve().parents[1];r=root/'build-grade2-incremental-bank4-decode-pair';n=root/(r.name+'-normalized');t=root/(r.name+'-timing');c=root/(r.name+'-coverage');paths=[r/'manifest.json',n/'manifest.json',t/'manifest.json',c/'report.json',Path('/tmp/tiny3tpu-nextpnr-placement-label-replay/manifest.json')];checked={}
for p in paths:
 m=json.loads(p.read_text());checked[str(p)]=digest(p)
 for key in ['sha256','output_sha256']:
  for f,h in m.get(key,{}).items():assert digest(f)==h,(p,f)
m=json.loads(paths[0].read_text());assert m['passed'] and all(m[k] for k in ['inputs_unchanged','logical_ports_exact','placements_exact','retained_routes_exact','ground_additions_only','normalized_ties_restored']);assert len(m['moves'])==15
assert '--no-place' not in m['command'] and '--force' not in m['command'];tool=Path(m['command'][0]);assert digest(tool)==json.loads(paths[-1].read_text())['tool_sha256']
coverage=json.loads(paths[3].read_text());assert coverage['native_fmax_reproduced'];v=json.loads(paths[2].read_text())['variants'];worst=[max(x['arrival_ns'] for x in probe['maxima']) for probe in v];assert worst==[10.218]*3
failing=[v for v in json.loads((t/'analysis-pcout-0-carry-0.1.json').read_text())['endpoints'] if v['arrival_ns']>10];assert len(failing)==18
record=dict(passed=True,route=str(r),expanded_intervals_ns=worst,failing_endpoint_domain_pairs=len(failing),logical_ports_exact=True,placement_only_state_change=False,register_locations_changed=13,lut_locations_changed=2,retained_route_aliases=len(m['retained_net_names']),released_route_aliases=len(m['released_net_names']),new_workload_simulation_run=False,full_soc_timing_accepted=False,scope='Candidate integrity and expanded diagnostic comparison only. Every logical cell/parameter/port matches parent; no architectural cycles added. Generic/carry delay qualification, skew/hold, reset recovery, DDR IO and hardware validation remain open.',sha256=checked|{str(t/'analysis-pcout-0-carry-0.1.json'):digest(t/'analysis-pcout-0-carry-0.1.json'),str(Path(__file__).resolve()):digest(Path(__file__).resolve())})
out=r/'iteration-integrity.json';assert not out.exists();out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record[k] for k in ['passed','expanded_intervals_ns','failing_endpoint_domain_pairs','full_soc_timing_accepted']}))
