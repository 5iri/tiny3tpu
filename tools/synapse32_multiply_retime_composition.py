#!/usr/bin/env python3
"""Bind the pipeline induction to the retained full arithmetic identity proof."""
import argparse,hashlib,importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'hardware/synapse32/experiments/boot-ddr-first'
sys.path.insert(0,str(HERE))
import multiply_single_csa as single
import multiply_retime as retime

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(p):
    d=json.loads(p.read_text());assert d['passed']
    for key in ['sha256','output_sha256']:
        for n,h in d.get(key,{}).items():assert digest(n)==h,(str(p),n)
    return d

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidate',type=Path,required=True);a=p.parse_args();c=a.candidate.resolve()
    out=c/'multiply-composition';out.mkdir(exist_ok=False)
    new_path=c/'multiply-proof/results.json';new=check(new_path)
    old_path=Path(new['parent_arithmetic_proof']);assert old_path==ROOT/'build-ddr-uart-prefix/multiply-proof/results.json';old=check(old_path)
    base=ROOT/'build-atomic-word-v2/overlay/alu.v';old_cpu=old_path.parents[1]/'overlay/alu.v';new_cpu=c/'overlay/alu.v'
    assert old_cpu.read_text()==single.patch_mul(base.read_text())
    assert new_cpu.read_text()==retime.patch_mul(base.read_text())
    assert old['sha256'][str(base)]==new['sha256'][str(base)]==digest(base)
    assert old['added_latency_cycles']==new['added_latency_cycles']==0
    paths=[Path(__file__).resolve(),new_path,old_path,base,old_cpu,new_cpu,HERE/'multiply_retime.py',HERE/'multiply_single_csa.py']
    record=dict(passed=True,added_latency_cycles=0,claim='The sequential induction gold is exactly the retained single-CSA CPU arithmetic candidate, whose arbitrary-partial-word identity to the original CPU is independently proved. Both proofs bind the same original CPU source. Result values and latency are preserved from common reset, with arbitrary subsequent resets and inputs. No physical timing claim.',checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [old_path,new_path]],sha256={str(q):digest(q) for q in paths})
    (out/'results.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS composed original arithmetic and register-boundary induction')
if __name__=='__main__':main()
