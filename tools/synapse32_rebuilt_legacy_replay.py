#!/usr/bin/env python3
"""Exact replay of the two legacy backends referenced by functional ancestry audits."""
import gc
gc.disable()
import argparse,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes import RecoveredHashes
from synapse32_timing_report import summarize
REFERENCES={'mixed-primitive-guidance':'build-ddr-uart-prefix-weight40-route/seed-4','cpu-preg-guidance':'build-ddr-cpu-preg-v2-weight40-route/seed-4'}
def main():
    p=argparse.ArgumentParser();p.add_argument('--backend',choices=REFERENCES,required=True);p.add_argument('--recovery',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();recovery=RecoveredHashes(a.recovery);ref=Path(REFERENCES[a.backend]).resolve();rp=ref/'manifest.json';old=json.loads(rp.read_text());assert old['optimization_run_accepted'] and old['inputs_unchanged'] and old['timing']['completed']
    tool=Path('/tmp')/('tiny3tpu-nextpnr-'+a.backend)/'nextpnr-xilinx';tool=tool.resolve();bp=tool.with_name('build-manifest.json');build=json.loads(bp.read_text());assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256'];allowed={str(tool),str(bp)};hashes={};subs=[]
    for key in ['sha256','output_sha256']:
        for n,h in old.get(key,{}).items():
            if str(Path(n).resolve()) in allowed:
                actual=digest(n);subs.append(dict(path=str(Path(n).resolve()),expected=h,actual=actual));hashes[n]=actual
            else:hashes[n]=recovery.check(n,h)
    assert {r['path'] for r in subs}==allowed
    for n,h in build['baseline_sha256'].items():assert digest(n)==h,n;hashes[n]=h
    command=old['command'].copy();assert Path(command[0]).resolve()==tool
    command[0]=str(tool)
    for flag,name in [('--write','routed.json'),('--report','report.json'),('--log','route.log')]:command[command.index(flag)+1]=str(out/name)
    assert not any(v in command for v in ['--force','--timing-allow-fail','--ignore-loops','--no-place','--no-pack','--fasm'])
    for q in [rp,a.recovery.resolve(),Path(__file__).resolve(),Path(__file__).with_name('synapse32_recovered_hashes.py')]:hashes[str(q)]=digest(q)
    out.mkdir();record=dict(passed=False,kind='rebuilt_legacy_exact_replay',backend=a.backend,recovery_reference=str(rp),recovery=recovery.metadata(),historical_substitutions=subs,command=command,sha256=hashes,full_soc_timing_accepted=False);mp=out/'manifest.json';mp.write_text(json.dumps(record,indent=2)+'\n')
    env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))};env.update(TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'),TINY3TPU_CARRY_GUIDANCE_PS=str(old['symbolic_carry_guidance_ps']),TINY3TPU_PRIMITIVE_GUIDANCE='1')
    with (out/'console.log').open('w') as f:rc=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
    record.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in hashes.items()),timing=summarize((out/'route.log').read_text(),exit_code=rc))
    record['routed_json_exact']=rc==0 and json.loads((out/'routed.json').read_text())==json.loads((ref/'routed.json').read_text());record['timing_graph_exact']=rc==0 and digest(out/'guidance-timing-graph.tsv')==digest(ref/'guidance-timing-graph.tsv')
    clocks=lambda r:{k:(v['mhz'],v['target_mhz'],v['status']) for k,v in r['timing']['final_clocks'].items()};record['native_fmax_exact']=clocks(record)==clocks(old);record['passed']=rc==0 and all(record[k] for k in ['inputs_unchanged','routed_json_exact','timing_graph_exact','native_fmax_exact']);record['output_sha256']={str(q):digest(q) for q in [out/n for n in ['routed.json','route.log','report.json','guidance-timing-graph.tsv']] if q.exists()};mp.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record[k] for k in ['passed','routed_json_exact','timing_graph_exact','native_fmax_exact']}));assert record['passed'],mp
if __name__=='__main__':main()
