#!/usr/bin/env python3
"""Measure physical resource reuse without treating partial timing as signoff."""
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--route',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();rp=a.route.resolve()/'manifest.json';r=json.loads(rp.read_text());assert r['passed'] and r['packed_logic_matches_patch'] and r['requested_placement_exact'] and r['routed_net_records']>1000
for k in ['sha256','output_sha256']:
 for n,h in r[k].items():assert digest(n)==h,n
cp=Path(r['input_checkpoint']);c=json.loads(cp.read_text());assert c['passed'] and c['routing_serialization_only_change'] and c['timing_graph_exact']
before_path=cp.parent/'pre-fixup.json';after_path=a.route.resolve()/'routed.json';before=json.loads(before_path.read_text());after=json.loads(after_path.read_text());assert functional_cells(before)[0]==functional_cells(after)[0]
x=before['modules']['top'];y=after['modules']['top'];assert set(y['netnames'])<=set(x['netnames'])
removed_names=set(x['netnames'])-set(y['netnames'])
used_bits={b for c in x['cells'].values() for bs in c['connections'].values() for b in bs}|{b for p in x['ports'].values() for b in p['bits']}
assert all(not x['netnames'][n].get('attributes',{}).get('ROUTING','').strip() and not set(x['netnames'][n]['bits'])&used_bits for n in removed_names)
def resources(v):
 text=v.get('attributes',{}).get('ROUTING','').strip()
 if not text:return []
 parts=text.split(';');assert len(parts)%3==0
 assert all(not parts[i] or '@ID=' in parts[i] for i in range(1,len(parts),3))
 return sorted((parts[i],parts[i+1]) for i in range(0,len(parts),3))
donor_cp=Path(r['reuse_checkpoint']);donor_path=donor_cp.parent/'pre-fixup.json';donor=json.loads(donor_path.read_text())['modules']['top']
nonempty=[n for n,v in donor['netnames'].items() if resources(v)];changed=[n for n in nonempty if resources(donor['netnames'][n])!=resources(y['netnames'].get(n,{}))]
imported=json.loads((a.route.resolve()/'input.json').read_text())['modules']['top']
kept=[n for n,v in imported['netnames'].items() if resources(v)]
assert len(kept)==r['routed_net_records']
changed_imported=[n for n in kept if resources(donor['netnames'][n])!=resources(y['netnames'].get(n,{}))]
raw_before=cp.parent/'guidance-timing-graph.tsv';raw_after=a.route.resolve()/'guidance-timing-graph.tsv'
record=dict(passed=True,removed_unconnected_unrouted_aliases=sorted(removed_names),logical_cells_exact=True,placement_changes=r['placement_changes'],imported_routed_nets=len(kept),unchanged_imported_routes=len(kept)-len(changed_imported),changed_imported_routes=changed_imported,original_routed_nets=len(nonempty),unchanged_routed_nets=len(nonempty)-len(changed),changed_routed_nets=changed,graph_exact=digest(raw_before)==digest(raw_after),full_soc_timing_accepted=False,scope='Actual nonempty routing was imported with exact pip IDs. Counts compare complete wire/pip resource sets, ignoring binding-strength and serialization order only. This is an observation of resource reuse; timing, physical connectivity, hold and DDR signoff are not implied.',checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [rp,cp,donor_cp]],sha256={str(q):digest(q) for q in [donor_path,before_path,after_path,raw_before,raw_after,Path(__file__).resolve(),Path(__file__).with_name('synapse32_pinmap_control_audit.py').resolve(),Path(__file__).with_name('synapse32_packed_equivalence.py').resolve()]})
if r.get('compatible_routes_locked'):assert not changed_imported, 'A locked imported route changed'
a.out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record[k] for k in ['passed','original_routed_nets','unchanged_routed_nets','imported_routed_nets','unchanged_imported_routes','graph_exact']}))
