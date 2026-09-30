#!/usr/bin/env python3
"""Check native mixed-output timing against independently evaluated microdesigns."""
import argparse,hashlib,json
from pathlib import Path
from synapse32_analyze_timing_graph import analyze
from synapse32_lutram_timing_model import limits_from_text
from synapse32_mixed_primitive_guidance_normalize import normalize_lutram

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];build=a.build.resolve();out=a.out.resolve();out.mkdir(exist_ok=False)
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
limits=limits_from_text((root/'build-dsp-preg-timing/ds182.txt').read_text());results=[];paths=[]
backend=Path('/tmp/tiny3tpu-nextpnr-mixed-primitive-guidance/build-manifest.json');manifest=json.loads(backend.read_text());assert manifest['passed'] and manifest['baseline_unchanged']
for n,h in manifest['baseline_sha256'].items():assert digest(n)==h,n
assert digest(backend.with_name('nextpnr-xilinx'))==manifest['tool_sha256']
for name in ['read-0','read-1','clock-origin-ram32m']:
    d=build/name;graph=d/'timing-graph.tsv';rows=[l.rstrip('\n').split('\t') for l in graph.open()]
    cells=next(iter(json.loads((d/'routed.json').read_text())['modules'].values()))['cells']
    legacy,coverage=normalize_lutram(rows,cells,limits)
    ram={n for n,c in cells.items() if c['attributes'].get('X_LUT_AS_DRAM','').strip()=='1'}
    result=analyze(graph,ram);assert not result['unresolved_nodes'] and result['visited']==result['nodes']
    maxima=[r for r in result['maxima'] if r['source_clock']==r['sink_clock']=='clk'];assert len(maxima)==1
    period=maxima[0]['arrival_ns'];native=json.loads((d/'report.json').read_text())['fmax']['clk']['achieved']
    assert abs(native-1000/period)<=.006,(name,native,period)
    removed_clock=[r for r in rows if not (r[0]=='CLOCK' and r[1] in ram and float(r[8])>0)]
    removed_read=[r for r in rows if not (r[0]=='CELLARC' and r[1] in ram)]
    mutants={}
    for label,variant in [('no-write-origin',removed_clock),('no-read-arcs',removed_read)]:
        f=out/(name+'-'+label+'.tsv');f.write_text('\n'.join('\t'.join(r) for r in variant)+'\n')
        alt=analyze(f);assert not alt['unresolved_nodes'] and alt['visited']==alt['nodes'];mutants[label]=max(r['arrival_ns'] for r in alt['maxima'] if r['source_clock']==r['sink_clock']=='clk');paths.append(f)
    if name=='clock-origin-ram32m':
        assert period > mutants['no-write-origin']+.1
        assert abs(max(r['arrival_ns'] for r in result['tracked_maxima'] if r['group']=='tracked_output')-period)<.001
    if name=='read-1': assert period > mutants['no-read-arcs']+1
    assert 'combinational loop' not in (d/'route.log').read_text().lower()
    results.append(dict(name=name,native_mhz=native,independent_period_ns=period,model=coverage,mutant_periods_ns=mutants))
    paths += [q for q in d.iterdir() if q.is_file()]
failed=build/'clock-origin/console.log';assert 'X_ORIG_TYPE' in failed.read_text() and 'RAMD32' in failed.read_text()
paths += [failed,build/'test.v',build/'test.xdc',build/'run.py',backend,backend.with_name('nextpnr-xilinx'),Path(__file__).resolve(),root/'tools/synapse32_mixed_primitive_guidance_normalize.py',root/'tools/synapse32_lutram_timing_model.py',root/'tools/synapse32_analyze_timing_graph.py',root/'build-dsp-preg-timing/ds182.txt']
record=dict(passed=True,tests=results,unsupported_ram_profile_rejected=True,
    claim='Native periods reproduce independent graphs for three routed RAMD32 microdesigns. Clock-only read test requires the write-clock origin; long asynchronous read test requires read arcs. Deliberately removing either reduces its corresponding critical interval. Unsupported RAM32X1D-derived profile fails closed. These are backend algorithm tests, not FPGA physical signoff.',full_soc_timing_accepted=False,
    sha256={str(q):digest(q) for q in paths})
(out/'results.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(dict(passed=True,tests=results)))
