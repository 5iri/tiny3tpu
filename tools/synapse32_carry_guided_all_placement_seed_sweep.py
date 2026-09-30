#!/usr/bin/env python3
"""Route with explicit symbolic carry guidance, then remove guidance for independent analysis.

All reported Fmax figures remain partial; registered DSP/LUTRAM and primitive
validation are incomplete. No whole-SoC closure is accepted by this driver.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
from synapse32_apply_bram_timing import apply_model, digest, limits_from_text
from synapse32_analyze_timing_graph import analyze
from synapse32_timing_report import summarize
from synapse32_missing_cell_arcs import audit as arc_audit
from synapse32_registered_dsp_model import GraphIndex


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seeds',type=int,nargs='+',default=[8,4]);p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--carry-ps',type=int,default=100,help='Symbolic optimization cost only, not a validated timing bound')
    a=p.parse_args();assert 0<=a.carry_ps<=1000
    assert a.jobs>0 and len(a.seeds)==len(set(a.seeds))
    root=Path(__file__).resolve().parents[1];board=a.board.resolve();out=a.out.resolve()
    tool=Path('/tmp/tiny3tpu-nextpnr-carry-guidance-all-placement/nextpnr-xilinx')
    build_path=tool.with_name('build-manifest.json');build=json.loads(build_path.read_text())
    assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
    for n,h in build['baseline_sha256'].items():assert digest(n)==h,n
    for n,k in [('arch.cc','source_sha256'),('arch.patch','patch_sha256'),('arch.o','object_sha256'),('carry_support.h','header_sha256')]:assert digest(tool.with_name(n))==build[k]
    replay_path=root/'build-carry-guidance-all-placement-disabled-replay/manifest.json';replay=json.loads(replay_path.read_text())
    assert replay['passed'] and replay['routed_json_exact'] and replay['timing_graph_exact'] and replay['native_fmax_exact']
    for key in ['sha256','output_sha256']:
        for n,h in replay[key].items():assert digest(n)==h,n
    assert replay['sha256'][str(tool)]==digest(tool)
    data=root/'build-dsp-preg-timing/ds182.txt';pdf=data.with_suffix('.pdf')
    proof_path=data.parent/'limits.json';proof=json.loads(proof_path.read_text())
    for q in (data,pdf):assert proof['sha256'][str(q)]==digest(q)
    limits=limits_from_text(data.read_text())
    chipdb=Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin')
    inputs=[tool,chipdb,build_path,replay_path,data,pdf,proof_path,
            board/'soc.json',board/'kc705.xdc',board/'firmware.hex',board/'synth.ys',
            Path(__file__).resolve(),root/'tools/synapse32_apply_bram_timing.py',
            root/'tools/synapse32_analyze_timing_graph.py',root/'tools/synapse32_timing_report.py',
            root/'tools/synapse32_missing_cell_arcs.py',root/'tools/synapse32_registered_dsp_model.py']
    hashes={str(q):digest(q) for q in inputs};hashes.update(build['baseline_sha256'])
    out.mkdir(parents=True,exist_ok=False)
    common=dict(scope=__doc__,sha256=hashes,board=str(board),seeds=a.seeds,
                limits=limits,target_mhz=100,symbolic_carry_guidance_ps=a.carry_ps,initial_placement_carry_coverage=True,full_soc_timing_accepted=False)
    (out/'inputs.json').write_text(json.dumps(common,indent=2)+'\n')

    def route(seed):
        dest=out/f'seed-{seed}';dest.mkdir()
        command=[str(tool),'--chipdb',str(chipdb),'--xdc',str(board/'kc705.xdc'),
                 '--freq','100','--seed',str(seed),'--json',str(board/'soc.json'),
                 '--write',str(dest/'routed.json'),'--report',str(dest/'report.json'),'--log',str(dest/'route.log')]
        record=dict(seed=seed,command=command,sha256=hashes,symbolic_carry_guidance_ps=a.carry_ps,initial_placement_carry_coverage=True,full_soc_timing_accepted=False)
        manifest=dest/'manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
        env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))}
        env['TINY3TPU_TIMING_GRAPH']=str(dest/'guidance-timing-graph.tsv')
        env['TINY3TPU_CARRY_GUIDANCE_PS']=str(a.carry_ps)
        with (dest/'console.log').open('w') as log:
            rc=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
        record['timing']=summarize((dest/'route.log').read_text(),exit_code=rc)
        record['inputs_unchanged']=all(digest(n)==h for n,h in hashes.items())
        record['no_combinational_loop_warning']='combinational loop' not in (dest/'route.log').read_text().lower()
        record['optimization_run_accepted']=rc==0 and record['inputs_unchanged'] and record['no_combinational_loop_warning']
        if record['optimization_run_accepted']:
            routed=dest/'routed.json';graph=dest/'timing-graph.tsv'
            cells=next(iter(json.loads(routed.read_text())['modules'].values()))['cells']
            raw=dest/'guidance-timing-graph.tsv'
            raw_lines=[l.rstrip('\n').split('\t') for l in raw.open()]
            removed=[v for v in raw_lines if v[0]=='CELLARC' and cells[v[1]]['type']=='CARRY4']
            assert removed and all(abs(float(v[4])*1000-a.carry_ps)<1e-4 for v in removed)
            lines=[v for v in raw_lines if not (v[0]=='CELLARC' and cells[v[1]]['type']=='CARRY4')]
            audit=arc_audit(lines,cells);ix=GraphIndex(lines,cells)
            expected={(v['cell'],v['input'],v['output']) for v in audit['missing_carry_arcs']}
            actual={(v[1],v[2],v[3]) for v in removed if ix.fanout[v[1],v[3]] and (v[1],v[2]) in ix.incoming}
            assert actual==expected, ('Carry guidance connectivity mismatch',list(expected-actual)[:5],list(actual-expected)[:5])
            graph.write_text(''.join('\t'.join(v)+'\n' for v in lines))
            removal=dict(scope='Only symbolic CARRY4 CELLARC rows are removed for comparison with baseline sensitivity models. No PORT, CLOCK or routed NETARC row is changed. Both raw and normalized graphs are retained.',
                         symbolic_carry_guidance_ps=a.carry_ps,removed_arc_count=len(removed),required_connected_arcs=len(expected),exact_boolean_support=True,
                         raw_sha256=digest(raw),normalized_sha256=digest(graph))
            (dest/'guidance-normalization.json').write_text(json.dumps(removal,indent=2)+'\n')
            record['carry_guidance_normalized']=True
            record['carry_guidance_support_exact']=True
            enhanced,decisions=apply_model(lines,cells,limits)
            annotated=dest/'bram-timing-graph.tsv';annotated.write_text(''.join('\t'.join(v)+'\n' for v in enhanced))
            analysis=analyze(annotated,tracked_cells={p['cell'] for p in decisions})
            (dest/'bram-analysis.json').write_text(json.dumps(analysis,indent=2)+'\n')
            (dest/'bram-decisions.json').write_text(json.dumps(decisions,indent=2)+'\n')
            record['graph_analysis_completed']=not analysis['unresolved_nodes']
            record['modeled_ram_count']=len({p['cell'] for p in decisions})
            record['expanded_maxima']=analysis['maxima']
            record['boot_ram_maxima']=[{k:v for k,v in m.items() if k!='path'} for m in analysis['tracked_maxima']]
            record['output_sha256']={str(q):digest(q) for q in [routed,graph,raw,dest/'guidance-normalization.json',annotated,dest/'bram-analysis.json',dest/'bram-decisions.json']}
        manifest.write_text(json.dumps(record,indent=2)+'\n')
        return record

    results=[]
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futures=[pool.submit(route,s) for s in a.seeds]
        for future in as_completed(futures):
            r=future.result();results.append(r)
            print(json.dumps({'seed':r['seed'],'clocks':r['timing']['final_clocks'],
                              'boot_ram_maxima':r.get('boot_ram_maxima'),
                              'full_soc_timing_accepted':False}),flush=True)
            (out/'results.json').write_text(json.dumps({'inputs':common,'results':results},indent=2)+'\n')


if __name__=='__main__':main()
