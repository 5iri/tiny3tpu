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
    p=argparse.ArgumentParser();p.add_argument('--control',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();control=a.control.resolve();out=a.out.resolve();assert not out.exists()
    root=Path(__file__).resolve().parents[1];rp=control/'manifest.json';source=json.loads(rp.read_text());assert source['passed'] and source['exit_code']==0
    for k in ['inputs_unchanged','logical_ports_exact','placements_exact','retained_routes_exact','ground_additions_only','normalized_ties_restored']:assert source[k]
    for k in ['sha256','output_sha256']:
        for n,h in source[k].items():assert digest(n)==h,n
    from synapse32_timing_report import summarize
    timing=summarize((control/'route.log').read_text(),exit_code=0);assert timing['completed']
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
    inputs=[rp,data,board_evidence,Path(__file__).resolve()]+[root/'tools'/n for n in ['synapse32_apply_bram_timing.py','synapse32_analyze_timing_graph.py','synapse32_missing_cell_arcs.py','synapse32_cpu_preg_dsp_model.py','synapse32_cpu_preg_mixed_normalize.py','synapse32_kc705_grade2_limits.py']]
    record=dict(passed=True,inputs_unchanged=True,timing=timing,graph_analysis_completed=True,carry_guidance_normalized=True,carry_guidance_support_exact=True,new_workload_simulation_run=False,full_soc_timing_accepted=False,scope='Expanded diagnostic normalization of exact-equivalent incremental placement route; no physical timing acceptance.',sha256={str(q):digest(q) for q in inputs},output_sha256={str(q):digest(q) for q in out.iterdir() if q.is_file()})
    (out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS incremental route normalization; expanded timing probes pending')
if __name__=='__main__':main()
