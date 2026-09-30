#!/usr/bin/env python3
"""Normalize a verified bounded fixed-layout route for independent expanded timing analysis."""
import gc
gc.disable()  # JSON/netlist trees are acyclic; retain normal reference counting.
import argparse,json,shutil
from pathlib import Path
from synapse32_apply_bram_timing import apply_model,digest
from synapse32_analyze_timing_graph import analyze
from synapse32_missing_cell_arcs import audit as arc_audit
from synapse32_cpu_preg_dsp_model import GraphIndex
from synapse32_cpu_preg_mixed_normalize import normalize as normalize_primitives
from synapse32_kc705_grade2_limits import bram_limits,dsp_limits,lutram_limits,verify_board

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--control',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();control=a.control.resolve();out=a.out.resolve();assert not out.exists()
    root=Path(__file__).resolve().parents[1];rp=control/'manifest.json';source=json.loads(rp.read_text())
    assert source['passed'] and source['pinmap_preservation_enabled'] and source['packed_logic_matches_patch'] and source['requested_placement_exact'] and source['input_logic_equivalent'] and source['clock_constraints_applied'] and source['timing']['completed']
    for k in ['sha256','output_sha256']:
        for n,h in source[k].items():assert digest(n)==h,n
    parent_path=Path(source['parent']);parent=json.loads(parent_path.read_text());assert parent['grade_selection'] and parent['domain_criticality_enabled']
    proof_path=Path(source['checkpoint']);proof=json.loads(proof_path.read_text());assert proof['passed']
    from synapse32_pinmap_control_audit import functional_cells
    golden=json.loads((proof_path.parent/'pre-fixup.json').read_text());routed=json.loads((control/'routed.json').read_text())
    from synapse32_packed_bank4_row_hit_collapse import apply_verified
    patch_path=Path(source['patch']);patch=json.loads(patch_path.read_text());assert patch['passed']
    for n,h in patch['sha256'].items():assert digest(n)==h,n
    golden=apply_verified(patch,golden)
    assert functional_cells(golden)[0]==functional_cells(routed)[0]
    original=json.loads((parent_path.parent/'routed.json').read_text())['modules']['top']['cells'];after=routed['modules']['top']['cells']
    assert (set(original)|set(patch['added_cells']))-set(patch['removed_cells'])==set(after)
    assert source['new_placement_exact'] and all(after[n]['attributes']['NEXTPNR_BEL']==patch['placements'][n] for n in patch['added_cells'])
    changed={n:[original[n]['attributes']['NEXTPNR_BEL'],c['attributes']['NEXTPNR_BEL']] for n,c in after.items() if n in original and original[n]['attributes']['NEXTPNR_BEL']!=c['attributes']['NEXTPNR_BEL']}
    assert changed==source['requested_placement_changes']==source['placement_changes']
    fixed_path=rp;fixed=source
    data=root/'build-dsp-preg-timing/ds182.txt';board_evidence=verify_board();limits=bram_limits(data.read_text())
    out.mkdir()
    for n in ['routed.json','guidance-timing-graph.tsv','route.log','report.json']:
        shutil.copyfile(control/n,out/n);assert digest(control/n)==digest(out/n)
    cells=json.loads((out/'routed.json').read_text())['modules']['top']['cells'];raw=out/'guidance-timing-graph.tsv';graph=out/'timing-graph.tsv'
    original=[line.rstrip('\n').split('\t') for line in raw.open()]
    removed=[v for v in original if v[0]=='CELLARC' and cells[v[1]]['type']=='CARRY4'];assert removed and all(abs(float(v[4])-.1)<1e-9 for v in removed)
    rows=[v for v in original if not(v[0]=='CELLARC' and cells[v[1]]['type']=='CARRY4')]
    rows,primitive=normalize_primitives(rows,cells,limits,dsp_limits(data.read_text()),lutram_limits(data.read_text()))
    audit=arc_audit(rows,cells);ix=GraphIndex(rows,cells)
    expected={(v['cell'],v['input'],v['output']) for v in audit['missing_carry_arcs']}
    actual={(v[1],v[2],v[3]) for v in removed if ix.fanout[v[1],v[3]] and (v[1],v[2]) in ix.incoming};assert actual==expected
    graph.write_text(''.join('\t'.join(v)+'\n' for v in rows));(out/'primitive-normalization.json').write_text(json.dumps(primitive,indent=2)+'\n')
    removal=dict(symbolic_carry_guidance_ps=100,removed_arc_count=len(removed),required_connected_arcs=len(expected),exact_boolean_support=True,raw_sha256=digest(raw),normalized_sha256=digest(graph))
    (out/'guidance-normalization.json').write_text(json.dumps(removal,indent=2)+'\n')
    enhanced,decisions=apply_model(rows,cells,limits);annotated=out/'bram-timing-graph.tsv';annotated.write_text(''.join('\t'.join(v)+'\n' for v in enhanced))
    analysis=analyze(annotated,tracked_cells={v['cell'] for v in decisions});assert not analysis['unresolved_nodes']
    (out/'bram-analysis.json').write_text(json.dumps(analysis,indent=2)+'\n');(out/'bram-decisions.json').write_text(json.dumps(decisions,indent=2)+'\n')
    hashes=dict(source['sha256']);hashes.update({str(q):digest(q) for q in [rp,proof_path,fixed_path,parent_path,data,board_evidence,Path(__file__).resolve()]})
    for name in ['synapse32_packed_bank4_row_hit_collapse.py','synapse32_apply_bram_timing.py','synapse32_analyze_timing_graph.py','synapse32_missing_cell_arcs.py','synapse32_cpu_preg_dsp_model.py','synapse32_cpu_preg_mixed_normalize.py','synapse32_kc705_grade2_limits.py','synapse32_pinmap_control_audit.py','synapse32_packed_equivalence.py']:hashes[str(root/'tools'/name)]=digest(root/'tools'/name)
    record=dict(passed=True,source_control=str(rp),command=source['command'],seed=5,sha256=hashes,checked_manifests=[dict(path=str(proof_path),sha256=digest(proof_path))],inputs_unchanged=True,timing=source['timing'],restored_parent_derived_clocks=fixed['restored_parent_derived_clocks'],grade_selection=parent['grade_selection'],domain_criticality_enabled=True,placement_beta=parent['placement_beta'],placement_timing_weight=parent['placement_timing_weight'],symbolic_carry_guidance_ps=100,carry_guidance_normalized=True,carry_guidance_support_exact=True,graph_analysis_completed=True,modeled_ram_count=len({v['cell'] for v in decisions}),new_route_run=False,new_workload_simulation_run=False,scope='Exact copy of a completed, equivalence-proved fixed-layout LUT, redundant-count-flag, same-edge refresher and timer-zero flags and proved dead-combinational-cone cleanup route. Only timing graph model rows are normalized for independent sensitivity analysis. Original derived clocks were restored without period changes; raw missing-derivation-log reasons remain. Not a new place/route run or physical timing acceptance.',full_soc_timing_accepted=False,output_sha256={str(q):digest(q) for q in out.iterdir() if q.is_file()})
    (out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS fixed-layout control graph normalization; no new route run or timing acceptance')

if __name__=='__main__':main()
