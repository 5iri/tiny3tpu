#!/usr/bin/env python3
"""Revalidate a rebuilt toolchain by exact replay, preserving historical manifests."""
import gc
gc.disable()
import argparse,copy,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_timing_report import summarize

ALLOWED={str(Path(p).resolve()) for p in [
 '/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx',
 *[f'/tmp/tiny3tpu-nextpnr-{v}/{f}' for v in ['timing-graph-observer','grade2-guidance','grade2-checkpoint','pinmap-preservation'] for f in ['nextpnr-xilinx','build-manifest.json']]]}

def main():
    p=argparse.ArgumentParser();p.add_argument('--reference',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();ref=a.reference.resolve();out=a.out.resolve();assert not out.exists()
    rp=ref/'manifest.json';old=json.loads(rp.read_text());ip=ref/'iteration-integrity.json';integrity=json.loads(ip.read_text());assert old['passed'] and old['packed_logic_matches_patch'] and integrity['passed'] and integrity['logical_cells_match_proved_patch']
    substitutions={};current={};objects=0
    def historical(path,expected):
        nonlocal objects
        q=Path(path);assert q.exists(),q;actual=digest(q);current[str(q)]=actual
        if str(q).endswith('.o'):objects+=1;assert actual==expected,('object changed',q)
        if actual!=expected:
            assert str(q.resolve()) in ALLOWED,('unapproved difference',q)
            key=str(q.resolve());row=dict(path=key,expected=expected,actual=actual)
            if key in substitutions:assert substitutions[key]==row
            substitutions[key]=row
    for data in [old,integrity]:
        for key in ['sha256','output_sha256']:
            for n,h in data.get(key,{}).items():historical(n,h)
    cp=Path(old['checkpoint']);checkpoint=json.loads(cp.read_text());assert checkpoint['passed']
    for key in ['sha256','output_sha256']:
        for n,h in checkpoint.get(key,{}).items():historical(n,h)
    assert objects>=38
    base=Path('/tmp/tiny3tpu-nextpnr-current')
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=base,text=True).strip()=='52d3cc889107db749e8d8ae93d3d50450a5d1979'
    subprocess.run(['git','diff','--exit-code'],cwd=base,check=True,stdout=subprocess.DEVNULL)
    for sub,rev in [('nextpnr-xilinx-meta','a4af910cac907f2cbd3a545f26f8e26573e860de'),('prjxray-db','e8b8e8e46a91334f6232df84d36954323e15a1d1')]:
        folder=base/'xilinx/external'/sub;assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=folder,text=True).strip()==rev;subprocess.run(['git','diff','--exit-code'],cwd=folder,check=True,stdout=subprocess.DEVNULL)
    tool=Path('/tmp/tiny3tpu-nextpnr-pinmap-preservation/nextpnr-xilinx').resolve();bp=tool.with_name('build-manifest.json');build=json.loads(bp.read_text());assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
    for folder in ['timing-graph-observer','grade2-guidance','grade2-checkpoint','pinmap-preservation']:
        manifest=Path('/tmp')/('tiny3tpu-nextpnr-'+folder)/'build-manifest.json';d=json.loads(manifest.read_text());assert d['passed'] and d['baseline_unchanged'];assert digest(manifest.with_name('nextpnr-xilinx'))==d['tool_sha256']
        for n,h in d['baseline_sha256'].items():assert digest(n)==h,n;current[n]=h
        current[str(manifest)]=digest(manifest)
    # The input JSON, clocks, firmware, chip database, proof files and graphs must
    # match their historical hashes; only the explicitly named rebuilt tools and
    # their build records may differ. No historical manifest is modified.
    command=old['command'].copy();command[0]=str(tool)
    for flag,name in [('--write','routed.json'),('--report','report.json'),('--log','route.log')]:command[command.index(flag)+1]=str(out/name)
    assert not any(v in command for v in ['--force','--timing-allow-fail','--ignore-loops','--no-place','--fasm'])
    for q in [rp,ip,cp,tool,bp,Path(__file__).resolve()]:current[str(q)]=digest(q)
    out.mkdir();record=copy.deepcopy(old);record.update(passed=False,kind='rebuilt_toolchain_exact_replay',recovery_reference=str(rp),recovery_integrity=str(ip),historical_substitutions=list(substitutions.values()),recovery_objects_checked=objects,command=command,sha256=current,output_sha256={},full_soc_timing_accepted=False)
    record['scope']='New run with rebuilt executables. All recorded original object files and all non-toolchain inputs match historical hashes. Require exact complete routed JSON, native graph and Fmax. Historical manifests are preserved; this is not physical timing acceptance.'
    output=out/'manifest.json';output.write_text(json.dumps(record,indent=2)+'\n')
    env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))};env.update(NEXTPNR_DUMP_INVALID_TILE='1',TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS='1',TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'),TINY3TPU_CARRY_GUIDANCE_PS=str(old['symbolic_carry_guidance_ps']),TINY3TPU_PRIMITIVE_GUIDANCE='1',TINY3TPU_DOMAIN_CRITICALITY='1',NEXTPNR_PLACER_BETA=str(old['placement_beta']))
    with (out/'console.log').open('w') as f:rc=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
    record.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in current.items()),timing=summarize((out/'route.log').read_text(),exit_code=rc))
    record['routed_json_exact']=rc==0 and json.loads((out/'routed.json').read_text())==json.loads((ref/'routed.json').read_text())
    record['timing_graph_exact']=rc==0 and digest(out/'guidance-timing-graph.tsv')==digest(ref/'guidance-timing-graph.tsv')
    clocks=lambda d:{k:(v['mhz'],v['target_mhz'],v['status']) for k,v in d['timing']['final_clocks'].items()}
    record['native_fmax_exact']=clocks(record)==clocks(old)
    record['passed']=rc==0 and all(record[k] for k in ['inputs_unchanged','routed_json_exact','timing_graph_exact','native_fmax_exact'])
    record['output_sha256']={str(q):digest(q) for q in [out/n for n in ['routed.json','route.log','report.json','guidance-timing-graph.tsv']] if q.exists()};output.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record[k] for k in ['passed','routed_json_exact','timing_graph_exact','native_fmax_exact']}));assert record['passed'],output
if __name__=='__main__':main()
