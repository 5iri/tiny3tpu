"""Audit the first sub-10 ns expanded candidate without claiming physical closure."""
import json
from pathlib import Path
from synapse32_apply_bram_timing import digest
root=Path(__file__).resolve().parents[1];r=root/'build-grade2-incremental-readvalid-arrival-swap';n=Path(str(r)+'-normalized');t=Path(str(r)+'-timing');c=Path(str(r)+'-coverage');files=[r/'manifest.json',r/'evaluation.json',n/'manifest.json',t/'manifest.json',c/'report.json',root/'build-grade2-readvalid-arrival-swap-proof/proof.json'];records={}
for p in files:
 d=json.loads(p.read_text());records[str(p)]=digest(p)
 for key in ['sha256','output_sha256']:
  for f,h in d.get(key,{}).items():assert digest(f)==h,(p,f)
route=json.loads(files[0].read_text());assert route['passed'] and route['logical_ports_exact'] and route['retained_routes_exact'] and route['placements_exact'];proof=json.loads(files[-1].read_text());assert proof['passed'] and proof['primitive_sat_passed'] and proof['exhaustive_cases']==256 and proof['added_latency_cycles']==0 and proof['added_cells']==proof['removed_cells']==0
coverage=json.loads((c/'report.json').read_text());assert coverage['native_fmax_reproduced'] and all(v['delay_ns']<=v['budget_ns'] for v in coverage['intervals']);timing=json.loads((n/'manifest.json').read_text())['timing'];assert all(v['status']=='PASS' and v['mhz']>=v['target_mhz'] for v in timing['final_clocks'].values());sensitivity=json.loads((t/'manifest.json').read_text());assert [max(v['arrival_ns'] for v in p['maxima']) for p in sensitivity['variants']]==[9.997]*3
assert not coverage['accepted'] and not any(coverage['validation'].values())
record=dict(diagnostic_milestone_passed=True,physical_goal_completed=False,native_system_mhz=timing['final_clocks']['clk']['mhz'],native_cpu_mhz=timing['final_clocks']['soc.cpu_clk']['mhz'],expanded_worst_ns=[9.997]*3,modeled_margin_ns=.003,all_reported_domain_intervals_within_budget=True,added_architectural_cycles=0,added_cells=0,primitive_equivalence_proved=True,new_workload_simulation_run=False,new_hardware_test_run=False,remaining_signoff_reasons=coverage['reasons'],validation=coverage['validation'],full_soc_timing_accepted=False,sha256=records|{str(Path(__file__).resolve()):digest(Path(__file__).resolve())})
p=r/'diagnostic-100mhz-milestone.json';assert not p.exists();p.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record[k] for k in ['diagnostic_milestone_passed','physical_goal_completed','native_system_mhz','expanded_worst_ns','modeled_margin_ns']}))
