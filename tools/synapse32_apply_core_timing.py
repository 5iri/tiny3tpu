#!/usr/bin/env python3
"""Compose explicit CPU DSP and boot-RAM timing; keep unknown cascade delay symbolic."""
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import apply_model as bram_model, limits_from_text as bram_limits, digest, ROOT
from synapse32_registered_dsp_model import apply_model as dsp_model, limits_from_text as dsp_limits
from synapse32_analyze_timing_graph import analyze
from synapse32_lutram_timing_model import apply_model as lutram_model, limits_from_text as lutram_limits
from synapse32_missing_cell_arcs import audit as arc_audit


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();replay=a.replay.resolve();out=a.out.resolve()
    parent=json.loads((replay/'manifest.json').read_text());assert parent['passed'] and parent['routed_json_exact']
    graph=replay/'timing-graph.tsv';routed=replay/'routed.json';assert digest(graph)==parent['graph_sha256']
    historical=json.loads(Path(parent['parent']).read_text());reference=Path(historical['command'][historical['command'].index('--write')+1])
    assert json.loads(reference.read_text())==json.loads(routed.read_text())
    text=ROOT/'build-dsp-preg-timing/ds182.txt';pdf=text.with_suffix('.pdf');proof_path=text.parent/'limits.json';proof=json.loads(proof_path.read_text())
    for q in [text,pdf]:assert digest(q)==proof['sha256'][str(q)]
    limits=dict(bram=bram_limits(text.read_text()),dsp=dsp_limits(text.read_text()),lutram=lutram_limits(text.read_text()))
    cells=next(iter(json.loads(routed.read_text())['modules'].values()))['cells']
    original=[l.rstrip('\n').split('\t') for l in graph.open()]
    rows,ram_decisions=bram_model(original,cells,limits['bram'])
    rows,lutram_coverage=lutram_model(rows,cells,limits['lutram'])
    missing_arcs=arc_audit(rows,cells)
    inputs=[graph,routed,replay/'manifest.json',reference,text,pdf,proof_path,Path(__file__).resolve(),
            ROOT/'tools/synapse32_apply_bram_timing.py',ROOT/'tools/synapse32_registered_dsp_model.py',ROOT/'tools/synapse32_analyze_timing_graph.py',ROOT/'tools/synapse32_lutram_timing_model.py',ROOT/'tools/synapse32_missing_cell_arcs.py']
    out.mkdir(parents=True,exist_ok=False);variants=[]
    (out/'missing-arcs.json').write_text(json.dumps(missing_arcs,indent=2)+'\n')
    (out/'lutram-coverage.json').write_text(json.dumps(lutram_coverage,indent=2)+'\n')
    for value in [0,1]:
        enhanced,coverage=dsp_model(rows,cells,limits['dsp'],pcout_ns=value)
        path=out/f'graph-pcout-{value}.tsv';path.write_text(''.join('\t'.join(v)+'\n' for v in enhanced))
        assert len({p['cell'] for p in coverage['unknown_delays']})==1
        targets={p['cell'] for p in coverage['unknown_delays']}
        result=analyze(path,tracked_cells=targets);assert not result['unresolved_nodes']
        (out/f'analysis-pcout-{value}.json').write_text(json.dumps(result,indent=2)+'\n')
        variants.append(dict(symbolic_pcout_ns=value,graph_sha256=digest(path),maxima=result['maxima'],
                             cascade_paths=[m for m in result['tracked_maxima'] if m['group']=='tracked_output']))
        if value==0:
            (out/'dsp-coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
    budgets=[]
    for first in variants[0]['cascade_paths']:
        matches=[m for m in variants[1]['cascade_paths'] if (m['source_clock'],m['source_edge'],m['sink_clock'],m['sink_edge'])==(first['source_clock'],first['source_edge'],first['sink_clock'],first['sink_edge'])]
        assert len(matches)==1 and abs(matches[0]['arrival_ns']-first['arrival_ns']-1)<1e-6
        # This exact current design's CPU and system nets both have a 10 ns
        # period. Require those domains instead of assigning unknown clocks.
        assert first['source_clock'] in ('clk','soc.cpu_clk') and first['sink_clock'] in ('clk','soc.cpu_clk')
        period=10 if first['source_edge']==first['sink_edge'] else 5
        budgets.append(dict(source_clock=first['source_clock'],sink_clock=first['sink_clock'],
                            required_max_clock_to_PCOUT_ns=round(period-first['arrival_ns'],9),
                            zero_substitution_path_ns=first['arrival_ns'],endpoint=[first['cell'],first['port']]))
    record=dict(scope='Registered DSP and boot-RAM graph coverage. PCOUT clock delay is an unknown parameter. Zero/one substitutions are sensitivity probes, not Fmax estimates or accepted timing bounds.',
                limits=limits,variants=variants,cascade_budgets=budgets,registered_dsp_count=len(coverage['profiles']),
                modeled_ram_count=len({p['cell'] for p in ram_decisions}),lutram_counts=lutram_coverage['counts'],
                model_application_completed=True,timing_audit_passed=missing_arcs['carry_arcs_complete'] and not coverage['unknown_delays'],
                missing_carry_arc_count=missing_arcs['missing_carry_arc_count'],full_soc_timing_accepted=False,
                sha256={str(q):digest(q) for q in inputs})
    (out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:record[k] for k in ['registered_dsp_count','modeled_ram_count','cascade_budgets','lutram_counts','missing_carry_arc_count','timing_audit_passed','full_soc_timing_accepted']},indent=2))
    print('Symbolic-zero known-model maxima:',json.dumps(variants[0]['maxima']))


if __name__=='__main__':main()
