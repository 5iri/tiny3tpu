#!/usr/bin/env python3
"""Route seeds with verified read-only graph export and boot-RAM timing audit.

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


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seeds',type=int,nargs='+',default=[8,4]);p.add_argument('--jobs',type=int,default=2)
    a=p.parse_args();assert a.jobs>0 and len(a.seeds)==len(set(a.seeds))
    root=Path(__file__).resolve().parents[1];board=a.board.resolve();out=a.out.resolve()
    tool=Path('/tmp/tiny3tpu-nextpnr-timing-graph-observer/nextpnr-xilinx')
    build_path=tool.with_name('build-manifest.json');build=json.loads(build_path.read_text())
    assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
    for n,h in build['baseline_sha256'].items():assert digest(n)==h,n
    for n,k in [('timing.cc','source_sha256'),('timing.patch','patch_sha256'),('timing.o','object_sha256')]:assert digest(tool.with_name(n))==build[k]
    replay_path=root/'build-ddr-timing-coverage-mid2/manifest.json';replay=json.loads(replay_path.read_text())
    assert replay['passed'] and replay['routed_json_exact'] and replay['fmax_reproduced']
    assert replay['sha256'][str(tool.resolve())]==digest(tool)
    data=root/'build-dsp-preg-timing/ds182.txt';pdf=data.with_suffix('.pdf')
    proof_path=data.parent/'limits.json';proof=json.loads(proof_path.read_text())
    for q in (data,pdf):assert proof['sha256'][str(q)]==digest(q)
    limits=limits_from_text(data.read_text())
    chipdb=Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin')
    inputs=[tool,chipdb,build_path,replay_path,data,pdf,proof_path,
            board/'soc.json',board/'kc705.xdc',board/'firmware.hex',board/'synth.ys',
            Path(__file__).resolve(),root/'tools/synapse32_apply_bram_timing.py',
            root/'tools/synapse32_analyze_timing_graph.py',root/'tools/synapse32_timing_report.py']
    hashes={str(q):digest(q) for q in inputs};hashes.update(build['baseline_sha256'])
    out.mkdir(parents=True,exist_ok=False)
    common=dict(scope=__doc__,sha256=hashes,board=str(board),seeds=a.seeds,
                limits=limits,target_mhz=100,full_soc_timing_accepted=False)
    (out/'inputs.json').write_text(json.dumps(common,indent=2)+'\n')

    def route(seed):
        dest=out/f'seed-{seed}';dest.mkdir()
        command=[str(tool),'--chipdb',str(chipdb),'--xdc',str(board/'kc705.xdc'),
                 '--freq','100','--seed',str(seed),'--json',str(board/'soc.json'),
                 '--write',str(dest/'routed.json'),'--report',str(dest/'report.json'),'--log',str(dest/'route.log')]
        record=dict(seed=seed,command=command,sha256=hashes,full_soc_timing_accepted=False)
        manifest=dest/'manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
        env={k:v for k,v in os.environ.items() if not k.startswith('NEXTPNR_')}
        env['TINY3TPU_TIMING_GRAPH']=str(dest/'timing-graph.tsv')
        with (dest/'console.log').open('w') as log:
            rc=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
        record['timing']=summarize((dest/'route.log').read_text(),exit_code=rc)
        record['inputs_unchanged']=all(digest(n)==h for n,h in hashes.items())
        if rc==0 and record['inputs_unchanged']:
            routed=dest/'routed.json';graph=dest/'timing-graph.tsv'
            cells=next(iter(json.loads(routed.read_text())['modules'].values()))['cells']
            lines=[l.rstrip('\n').split('\t') for l in graph.open()]
            enhanced,decisions=apply_model(lines,cells,limits)
            annotated=dest/'bram-timing-graph.tsv';annotated.write_text(''.join('\t'.join(v)+'\n' for v in enhanced))
            analysis=analyze(annotated,tracked_cells={p['cell'] for p in decisions})
            (dest/'bram-analysis.json').write_text(json.dumps(analysis,indent=2)+'\n')
            (dest/'bram-decisions.json').write_text(json.dumps(decisions,indent=2)+'\n')
            record['graph_analysis_completed']=not analysis['unresolved_nodes']
            record['modeled_ram_count']=len({p['cell'] for p in decisions})
            record['expanded_maxima']=analysis['maxima']
            record['boot_ram_maxima']=[{k:v for k,v in m.items() if k!='path'} for m in analysis['tracked_maxima']]
            record['output_sha256']={str(q):digest(q) for q in [routed,graph,annotated,dest/'bram-analysis.json',dest/'bram-decisions.json']}
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
