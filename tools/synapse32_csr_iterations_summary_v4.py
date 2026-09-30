#!/usr/bin/env python3
"""Hash-check the full CSR/primitive iteration set, retaining regressions and pending work."""
import argparse,hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RECORDS=[
('CSR predecode','build-ddr-csr-predecode/iteration-integrity.json'),
('DDR read credit','build-ddr-csr-read-credit/iteration-integrity.json'),
('Blocked multiply, carry guidance','build-ddr-csr-mul-blocks/iteration-integrity.json'),
('Blocked multiply, primitive guidance','build-ddr-csr-mul-blocks/primitive-integrity.json'),
('Dual DMA, primitive guidance','build-ddr-dual-dma-advance/iteration-integrity.json'),
('Local DMA/TPU acceptance','build-ddr-local-dma-tpu/iteration-integrity.json'),
('Atomic and divider','build-ddr-local-atomic-divider/iteration-integrity.json'),
('Direct burst counts','build-ddr-direct-burst-counts/iteration-integrity.json'),
('CSR readback','build-ddr-csr-readback/iteration-integrity.json'),
('Dual DMA, mixed guidance','build-ddr-dual-dma-advance/mixed-integrity.json'),
('CSR readback, mixed guidance','build-ddr-csr-readback/mixed-integrity.json'),
('Dual DMA, mixed weight40 seed4','build-ddr-dual-dma-advance/weight40-integrity.json'),
('Dual DMA, mixed weight40 seed8','build-ddr-dual-dma-advance/weight40-seed8-integrity.json'),
('Dual DMA, mixed weight100 seed4','build-ddr-dual-dma-advance/weight100-integrity.json'),
('Counts/readback without local acceptance','build-ddr-count-readback-no-local/iteration-integrity.json'),
('Single CSA multiplier','build-ddr-single-csa/iteration-integrity.json'),
('DDR signed offsets','build-ddr-signed-offsets/iteration-integrity.json'),
('Single CSA multiplier seed4','build-ddr-single-csa/seed4-integrity.json'),
('Parallel DMA alternatives','build-ddr-parallel-dma/iteration-integrity.json'),
('Balanced multiplier prefix','build-ddr-mul-prefix/iteration-integrity.json'),
('Kept DDR offset alternatives','build-ddr-kept-offsets/iteration-integrity.json'),
('Prefix DDR offset alternatives','build-ddr-prefix-offsets/iteration-integrity.json'),
('Prefix DDR offset alternatives seed4','build-ddr-prefix-offsets/seed4-integrity.json'),
('Parallel DDR address comparison','build-ddr-parallel-compare/iteration-integrity.json'),
]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists()
    hashes={};seen=set()
    def digest(path):
        path=Path(path).resolve()
        if str(path) not in hashes:
            h=hashlib.sha256()
            with path.open('rb') as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
            hashes[str(path)]=h.hexdigest()
        return hashes[str(path)]
    def verify(path):
        path=Path(path).resolve();data=json.loads(path.read_text());digest(path)
        if path in seen:return data
        seen.add(path)
        for k in ['sha256','output_sha256']:
            for n,h in data.get(k,{}).items():assert digest(n)==h,(str(path),n)
        for r in data.get('checked_manifests',[]):
            assert digest(r['path'])==r['sha256'];verify(r['path'])
        return data
    baseline=ROOT/'build-ddr-uart-reset-guided8-timing-sensitivity/manifest.json';base=verify(baseline)
    original=[max(r['arrival_ns'] for r in v['maxima']) for v in base['variants']]
    gate=verify(ROOT/'build-soc-timing-check-best-expanded-final/report.json');assert not gate['accepted']
    selected=dict(name='Retained baseline',worst_probe_ns=max(original),model=str(baseline.parent),physical_timing_accepted=False)
    records=[]
    for name,relative in RECORDS:
        path=ROOT/relative
        if not path.exists():
            records.append(dict(name=name,status='pending',expected_integrity=str(path)));continue
        d=verify(path);assert d['passed'] and not d['full_soc_timing_accepted']
        route=verify(Path(d['route'])/'manifest.json');assert route['inputs_unchanged'] and route['timing']['completed'] and route['graph_analysis_completed']
        native={k:v['mhz'] for k,v in route['timing']['final_clocks'].items()}
        row=dict(name=name,status='verified_diagnostic_only',candidate=d['candidate'],route=d['route'],integrity=str(path),expanded_probes_ns=d['expanded_intervals_ns'],native_mhz=native,functional=d['functional'],full_soc_timing_accepted=False)
        if route.get('placement_timing_weight') is not None:
            config=verify(Path(d['route']).parent/'placement-settings.json')
            assert config['logical_netlist_exact'] and not config['clock_constraints_changed']
            original_net=json.loads((Path(d['candidate'])/'board/soc.json').read_text())
            configured=json.loads((Path(d['route']).parent/'placement-input.json').read_text())
            assert configured['modules']['kc705_synapse32_top'].pop('settings')==config['settings']
            assert set(config['settings'])=={'placerHeap/timingWeight'} and configured==original_net
            row['placement_timing_weight']=route['placement_timing_weight']
        records.append(row)
        worst=max(row['expanded_probes_ns'])
        if worst<selected['worst_probe_ns']:
            selected=dict(name=name,worst_probe_ns=worst,integrity=str(path),physical_timing_accepted=False)
    controls=[]
    for relative in ['build-primitive-guidance-disabled-replay/manifest.json','build-mixed-primitive-guidance-disabled-replay/manifest.json','build-mixed-lutram-microtests/audit-v2/results.json']:
        q=ROOT/relative;d=verify(q);assert d['passed'];controls.append(str(q))
    digest(__file__)
    result=dict(passed=True,scope='Artifact integrity and same-workload throughput. Models retain symbolic carry substitutions and unvalidated physical timing. Pending work is not accepted; no native-only MHz result replaces expanded checks.',baseline_probes_ns=original,records=records,selected_expanded_diagnostic=selected,controls=controls,
        rejected_attempts=[dict(path='build-ddr-csr-readback-mixed-timing',reason='Disk-full report write; use fresh -retry result'),dict(path='build-ddr-dual-dma-mixed-coverage',reason='Disk-full report write; use fresh -retry result'),dict(path='/tmp/tiny3tpu-nextpnr-primitive-guidance',reason='Unavailable Property accessor; failed compile, superseded by v2'),dict(path='build-mixed-lutram-microtests/clock-origin',reason='Unsupported RAM32X1D-derived profile correctly rejected; RAM32M replacement passed')],
        full_soc_timing_accepted=False,sha256=hashes)
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(verified_routes=sum(r['status']=='verified_diagnostic_only' for r in records),pending=sum(r['status']=='pending' for r in records),selected=selected,checked_hashes=len(hashes),full_soc_timing_accepted=False)))

if __name__=='__main__':main()
