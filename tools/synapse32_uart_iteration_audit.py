#!/usr/bin/env python3
"""Recheck UART iteration provenance, exact functional results and routed comparisons."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
records=[]
def check(path):
    path=ROOT/path
    data=json.loads(path.read_text())
    count=0
    for key in ('sha256','output_sha256'):
        for name,value in data.get(key,{}).items():
            assert digest(name)==value,(str(path),name)
            count+=1
    records.append(dict(manifest=str(path),sha256=digest(path),checked_hashes=count))
    return data
proofs=[]
for folder in ('build-uart-local-burst-proof','build-uart-zero-flags-proved'):
    proof=check(Path(folder)/'results.json');assert proof['passed']
    synth=check(Path(folder)/'synthesis-comparison.json')
    assert synth['firmware_identical'] and synth['constraints_identical']
    proofs.append(folder)
functional=[]
for kind in ('dma','gemm'):
    baseline=ROOT/f'build-ddr-{kind}-burst-limit/system/results.json'
    original=json.loads(baseline.read_text())
    for name in ('uart-local-burst-verified','uart-zero-burst'):
        path=Path(f'build-ddr-{kind}-{name}/system/results.json')
        data=check(path)
        assert all(original[k]==data[k] for k in ('profile','metrics','dma'))
        if name=='uart-local-burst-verified':
            previous=json.loads((ROOT/f'build-ddr-{kind}-uart-local-burst/system/results.json').read_text())
            assert all(previous[k]==data[k] for k in ('profile','metrics','dma'))
            # The first runs predate the independent UART-zero driver option.
            # Preserve historical manifests; fresh runs bind current driver and RTL.
            for old,value in previous['sha256'].items():
                if old.endswith('/dma/run.py'):continue
                assert digest(old)==value,old
            for rtl in ('synapse32_dram_soc.sv','uart.v','axi_dma_rd.v','axi_dma_wr.v','csr_file.v','synapse32_memory_sequencer.sv','tpu_core_wrapper.sv','stream_smoke.c'):
                assert (ROOT/f'build-ddr-{kind}-uart-local-burst'/rtl).read_bytes()==(ROOT/f'build-ddr-{kind}-{name}'/rtl).read_bytes(),rtl
        functional.append(dict(kind=kind,candidate=name,all_profile_metrics_dma_exact=True,baseline_sha256=digest(baseline),cpu_ipc=data['profile']['instructions']/data['profile']['cpu_edges'],system_cycles=data['metrics']['system_cycles'],memory_model=data['metrics']['memory_model'],litedram_frontend_simulated=data['configuration']['litedram_frontend_simulated']))
routes=[]
for prefix,seeds,analysis in [
    ('build-ddr-seeds-uart-local-burst-graph',(4,8),'build-ddr-uart-local-burst'),
    ('build-ddr-seeds-uart-zero-burst-graph',(4,8),'build-ddr-uart-zero-burst'),
    ('build-ddr-seeds-burst-limit-extra-graph',(2,7),'build-ddr-burst-limit'),
    ('build-ddr-seeds-carry-guided-placed-uart-local-graph',(4,8),'build-ddr-carry-guided-placed-uart-local'),
]:
    for seed in seeds:
        path=Path(prefix)/f'seed-{seed}'
        route=check(path/'manifest.json')
        timing=check(Path(f'{analysis}{seed}-timing-sensitivity/manifest.json'))
        assert route['inputs_unchanged'] and route['timing']['completed'] and route['graph_analysis_completed']
        assert 'combinational loop' not in (ROOT/path/'route.log').read_text().lower()
        assert not timing['full_soc_timing_accepted'] and not timing['timing_audit_passed']
        for variant in timing['variants']:
            filename=f"graph-pcout-{variant['symbolic_pcout_ns']}-carry-{variant['symbolic_carry_arc_ns']}.tsv"
            assert digest(ROOT/f'{analysis}{seed}-timing-sensitivity'/filename)==variant['graph_sha256']
        if 'carry-guided-placed' in prefix:
            assert all(route[k] for k in ('no_combinational_loop_warning','optimization_run_accepted','carry_guidance_normalized','carry_guidance_support_exact'))
            norm=json.loads((ROOT/path/'guidance-normalization.json').read_text())
            assert norm['exact_boolean_support'] and norm['required_connected_arcs']==10924
        maxima=[round(max(x['arrival_ns'] for x in v['maxima']),6) for v in timing['variants']]
        routes.append(dict(route=str(path),native_partial_clocks=route['timing']['final_clocks'],symbolic_intervals_ns=maxima))
replay=check(Path('build-carry-guidance-placed-disabled-replay/manifest.json'))
assert all(replay[k] for k in ('passed','inputs_unchanged','routed_json_exact','timing_graph_exact','native_fmax_exact'))
selected=next(r for r in routes if r['route']=='build-ddr-seeds-carry-guided-placed-uart-local-graph/seed-4')
assert all(all(a<=b for a,b in zip(selected['symbolic_intervals_ns'],r['symbolic_intervals_ns'])) for r in routes)
record=dict(passed=True,scope='Exact functional and artifact checks. Timing intervals use symbolic carry/PCOUT delays and do not establish physical Fmax. Throughput runs use the recorded variable-latency memory model, not LiteDRAM/PHY or hardware.',proofs=proofs,functional=functional,routes=routes,selected=selected['route'],full_soc_timing_accepted=False,checked_manifests=records,script_sha256=digest(Path(__file__)))
out=ROOT/'build-uart-local-burst-proof/iteration-integrity.json'
out.write_text(json.dumps(record,indent=2)+'\n')
print('PASS',len(records),'manifests;',len(routes),'routes; exact smoke and 45-shape performance; selected',record['selected'])
