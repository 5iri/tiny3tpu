#!/usr/bin/env python3
"""Route with explicit symbolic carry guidance, then remove guidance for independent analysis.

The native model includes boot RAM, pure MREG DSPs, mixed LUTRAM and symbolic carry arcs.
All reported Fmax figures remain partial: physical primitive/routing/clock validation is incomplete. No whole-SoC closure is accepted by this driver.
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
from synapse32_cpu_preg_dsp_model import GraphIndex, limits_from_text as dsp_limits
from synapse32_lutram_timing_model import limits_from_text as lutram_limits
from synapse32_cpu_preg_mixed_normalize import normalize as normalize_primitives
from synapse32_kc705_grade2_limits import bram_limits as limits_from_text,dsp_limits,lutram_limits,verify_board


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seeds',type=int,nargs='+',default=[8,4]);p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--carry-ps',type=int,default=100,help='Symbolic optimization cost only, not a validated timing bound')
    p.add_argument('--timing-weight',type=int,required=True)
    p.add_argument('--beta',type=float,default=.4,help='Legal placement density target; no timing constraint change')
    a=p.parse_args();assert 1<=a.timing_weight<=100
    assert 0<=a.carry_ps<=1000 and .3<=a.beta<=.7
    board_evidence=verify_board()
    assert a.jobs>0 and len(a.seeds)==len(set(a.seeds))
    root=Path(__file__).resolve().parents[1];board=a.board.resolve();out=a.out.resolve()
    tool=Path('/tmp/tiny3tpu-nextpnr-free-dsp-slots/nextpnr-xilinx').resolve()
    grade_dir=Path('/tmp/tiny3tpu-nextpnr-grade2-guidance').resolve();grade_path=grade_dir/'build-manifest.json';grade=json.loads(grade_path.read_text());assert grade['passed'] and grade['baseline_unchanged']
    for n,h in grade['baseline_sha256'].items():assert digest(n)==h,n
    build_path=tool.with_name('build-manifest.json');build=json.loads(build_path.read_text())
    assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
    for n,h in build['baseline_sha256'].items():assert digest(n)==h,n
    for n,k in [('pack_dsp_xc7.cc','source_sha256'),('pack_dsp.patch','patch_sha256'),('pack_dsp.o','object_sha256')]:assert digest(tool.with_name(n))==build[k]
    assert digest(grade_dir/'domain_criticality.h')==grade['domain_header_sha256']
    tests_path=root/'build-free-dsp-slots-pack-tests-v2/results.json';tests=json.loads(tests_path.read_text());assert tests['passed'] and [v['released'] for v in tests['tests']]==[36,34]
    for k in ['sha256','output_sha256']:
        for n,h in tests[k].items():assert digest(n)==h,n
    replay_path=root/'build-free-dsp-slots-disabled-replay/manifest.json';replay=json.loads(replay_path.read_text())
    assert replay['passed'] and replay['routed_json_exact'] and replay['timing_graph_exact'] and replay['native_fmax_exact']
    for key in ['sha256','output_sha256']:
        for n,h in replay[key].items():assert digest(n)==h,n
    assert replay['sha256'][str(tool)]==digest(tool)
    data=root/'build-dsp-preg-timing/ds182.txt';pdf=data.with_suffix('.pdf')
    proof_path=data.parent/'limits.json';proof=json.loads(proof_path.read_text())
    for q in (data,pdf):assert proof['sha256'][str(q)]==digest(q)
    limits=limits_from_text(data.read_text())
    chipdb=Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin')
    inputs=[board_evidence,root/'tools/synapse32_kc705_grade2_limits.py',tool,grade_dir/'domain_criticality.h',grade_path,tests_path,chipdb,build_path,replay_path,data,pdf,proof_path,
            board/'soc.json',board/'kc705.xdc',board/'firmware.hex',board/'synth.ys',
            Path(__file__).resolve(),root/'tools/synapse32_apply_bram_timing.py',
            root/'tools/synapse32_analyze_timing_graph.py',root/'tools/synapse32_timing_report.py',
            root/'tools/synapse32_missing_cell_arcs.py',root/'tools/synapse32_cpu_preg_dsp_model.py',root/'tools/synapse32_cpu_preg_mixed_normalize.py',root/'tools/synapse32_cpu_preg_guidance_normalize.py',root/'tools/synapse32_lutram_timing_model.py']
    hashes={str(q):digest(q) for q in inputs};hashes.update(build['baseline_sha256'])
    out.mkdir(parents=True,exist_ok=False)
    original=json.loads((board/'soc.json').read_text())
    assert not original['modules']['kc705_synapse32_top'].get('settings')
    configured=json.loads((board/'soc.json').read_text())
    configured['modules']['kc705_synapse32_top']['settings']={'placerHeap/timingWeight':a.timing_weight}
    netlist=out/'placement-input.json';netlist.write_text(json.dumps(configured,separators=(',',':'))+'\n')
    restored=json.loads(netlist.read_text());settings=restored['modules']['kc705_synapse32_top'].pop('settings')
    assert restored==original
    config_record=out/'placement-settings.json'
    config_record.write_text(json.dumps(dict(passed=True,logical_netlist_exact=True,settings=settings,
        clock_constraints_changed=False,sha256={str(board/'soc.json'):digest(board/'soc.json'),str(netlist):digest(netlist)}),indent=2)+'\n')
    hashes.update({str(netlist):digest(netlist),str(config_record):digest(config_record)})
    common=dict(scope=__doc__,sha256=hashes,board=str(board),seeds=a.seeds,
                limits=limits,target_mhz=100,symbolic_carry_guidance_ps=a.carry_ps,initial_placement_carry_coverage=True,primitive_guidance_enabled=True,domain_criticality_enabled=True,standalone_dsp_slots_enabled=True,placement_timing_weight=a.timing_weight,placement_beta=a.beta,grade_selection="DS182 1.0 V -2/-2LE registered DSP/RAM/LUTRAM profiles",full_soc_timing_accepted=False)
    (out/'inputs.json').write_text(json.dumps(common,indent=2)+'\n')

    def route(seed):
        dest=out/f'seed-{seed}';dest.mkdir()
        command=[str(tool),'--chipdb',str(chipdb),'--xdc',str(board/'kc705.xdc'),
                 '--freq','100','--seed',str(seed),'--json',str(netlist),
                 '--write',str(dest/'routed.json'),'--report',str(dest/'report.json'),'--log',str(dest/'route.log')]
        record=dict(seed=seed,command=command,sha256=hashes,symbolic_carry_guidance_ps=a.carry_ps,initial_placement_carry_coverage=True,primitive_guidance_enabled=True,domain_criticality_enabled=True,standalone_dsp_slots_enabled=True,placement_timing_weight=a.timing_weight,placement_beta=a.beta,grade_selection="DS182 1.0 V -2/-2LE registered DSP/RAM/LUTRAM profiles",full_soc_timing_accepted=False)
        manifest=dest/'manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
        env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))}
        env['TINY3TPU_TIMING_GRAPH']=str(dest/'guidance-timing-graph.tsv')
        env['TINY3TPU_CARRY_GUIDANCE_PS']=str(a.carry_ps)
        env['TINY3TPU_PRIMITIVE_GUIDANCE']='1'
        env['TINY3TPU_DOMAIN_CRITICALITY']='1'
        env['TINY3TPU_FREE_STANDALONE_DSP_SLOTS']='1'
        env['NEXTPNR_PLACER_BETA']=str(a.beta)
        record['domain_criticality_enabled']=True
        with (dest/'console.log').open('w') as log:
            rc=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
        assert f'HeAP congestion knobs: beta={a.beta:.3f}' in (dest/'route.log').read_text()
        record['timing']=summarize((dest/'route.log').read_text(),exit_code=rc)
        record['inputs_unchanged']=all(digest(n)==h for n,h in hashes.items())
        record['no_combinational_loop_warning']='combinational loop' not in (dest/'route.log').read_text().lower()
        record['optimization_run_accepted']=rc==0 and record['inputs_unchanged'] and record['no_combinational_loop_warning']
        if record['optimization_run_accepted']:
            routed=dest/'routed.json';graph=dest/'timing-graph.tsv'
            cells=next(iter(json.loads(routed.read_text())['modules'].values()))['cells']
            dsp_bels={n:c['attributes']['NEXTPNR_BEL'] for n,c in cells.items() if c['type']=='DSP48E1_DSP48E1'}
            record['dsp_bels']=dsp_bels;record['upper_slot_dsp_count']=sum(int(v.split('Y')[1].split('/')[0])%2 for v in dsp_bels.values())
            raw=dest/'guidance-timing-graph.tsv'
            raw_lines=[l.rstrip('\n').split('\t') for l in raw.open()]
            removed=[v for v in raw_lines if v[0]=='CELLARC' and cells[v[1]]['type']=='CARRY4']
            assert removed and all(abs(float(v[4])*1000-a.carry_ps)<1e-4 for v in removed)
            lines=[v for v in raw_lines if not (v[0]=='CELLARC' and cells[v[1]]['type']=='CARRY4')]
            lines,primitive_check=normalize_primitives(lines,cells,limits,dsp_limits(data.read_text()),lutram_limits(data.read_text()))
            (dest/'primitive-normalization.json').write_text(json.dumps(primitive_check,indent=2)+'\n')
            audit=arc_audit(lines,cells);ix=GraphIndex(lines,cells)
            expected={(v['cell'],v['input'],v['output']) for v in audit['missing_carry_arcs']}
            actual={(v[1],v[2],v[3]) for v in removed if ix.fanout[v[1],v[3]] and (v[1],v[2]) in ix.incoming}
            assert actual==expected, ('Carry guidance connectivity mismatch',list(expected-actual)[:5],list(actual-expected)[:5])
            graph.write_text(''.join('\t'.join(v)+'\n' for v in lines))
            removal=dict(scope='Only added carry arcs and independently checked RAM/MREG classifications and clock rows are normalized for baseline sensitivity models. No routed NETARC row changes. Raw native graph retained.',
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
            record['output_sha256']={str(q):digest(q) for q in [routed,graph,raw,dest/'guidance-normalization.json',annotated,dest/'bram-analysis.json',dest/'bram-decisions.json',dest/'primitive-normalization.json']}
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
