"""Require exact seed-5 replay after removing stale imported RNG metadata."""
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);p.add_argument('--replay',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();old=a.reference.resolve();new=a.replay.resolve();refs=[old/'manifest.json',new/'manifest.json'];records=[json.loads(p.read_text()) for p in refs];paths=[*refs,Path(__file__)]
for r in records:
 assert r['passed'] and r['timing']['completed'] and r['packed_logic_matches_patch'] and r['requested_placement_exact'] and r['clock_constraints_applied']
 for k in ['sha256','output_sha256']:
  for n,h in r[k].items():assert digest(n)==h,n;paths.append(Path(n))
assert records[1]['input_seed_metadata_removed'] and records[1]['actual_seed_verified'] and records[1]['seed']==5
for r in records:assert r['command'][r['command'].index('--seed')+1]=='5'
for name in ['routed.json','guidance-timing-graph.tsv']:assert digest(old/name)==digest(new/name)
assert records[0]['timing']['final_clocks']==records[1]['timing']['final_clocks'];original=json.loads((old/'input.json').read_text());replay=json.loads((new/'input.json').read_text())
for m in original['modules'].values():assert 'seed' in m['settings'] and 'seed.arg' in m['settings'];m['settings'].pop('seed');m['settings'].pop('seed.arg')
assert original==replay and all('seed' not in m['settings'] and 'seed.arg' not in m['settings'] for m in replay['modules'].values())
actual=json.loads((new/'routed.json').read_text());assert int(actual['modules']['top']['settings']['seed.arg'],2)==5
rejected=Path('build-toolchain-recovery/branch-seed-baseline-4-route-driver.log').resolve();assert "int(actual['modules']['top']['settings']['seed.arg'],2)==a.seed" in rejected.read_text() and 'AssertionError' in rejected.read_text();paths.extend([rejected,old/'input.json',new/'input.json'])
a.out.write_text(json.dumps(dict(passed=True,reference=str(old),replay=str(new),input_difference_only_removed_seed_metadata=True,routed_json_exact=True,timing_graph_exact=True,native_clocks_exact=True,stale_metadata_run_rejected=True,full_soc_timing_accepted=False,scope='Command handling initializes the live RNG before JSON import; stale imported settings were overwriting its recorded seed fields. Removing only those fields gives an exact full seed-5 replay. Subsequent runs must record the requested seed and pass complete independent route/timing audits. No timing-model or physical acceptance change.',sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print('PASS seed metadata fix: exact routed JSON, timing graph and native clock replay')
