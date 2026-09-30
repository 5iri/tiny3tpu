"""Compose existing atomic/divider rewrites without changing their proof helpers."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]

def module(name):
    path=HERE.parent/name/'prepare.py'
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result

atomic=module('atomic-select')
divider=module('divider-sign-select')

def patch_atomic(source):
    old='    atomic_lsu atomic_lsu_inst0 ('
    new='    atomic_lsu_parallel atomic_lsu_inst0 ('
    assert source.count(old)==1
    gate=atomic.patch(atomic.ATOMIC.read_text())
    result=source.replace(old,new)+'\n'+gate
    assert result[:-len('\n'+gate)].replace(new,old)==source
    return result

def patch_divider(source):
    return divider.patch(source)

def prove_atomic_divider(out):
    proof=out/'atomic-divider-proof';proof.mkdir(exist_ok=False)
    source=proof/'source';source.mkdir()
    parent=ROOT/'build-ddr-local-dma-tpu/overlay'
    for src in parent.glob('*.v'):
        (source/src.name).write_bytes(src.read_bytes())
    for name,src,dest in [('atomic-select',source,proof/'atomic'),
                          ('divider-sign-select',proof/'atomic/overlay',proof/'divider')]:
        with (proof/(name+'.log')).open('w') as log:
            subprocess.run([sys.executable,str(HERE.parent/name/'prove.py'),'--source',str(src),'--out',str(dest)],stdout=log,stderr=subprocess.STDOUT,check=True)
        data=json.loads((dest/'results.json').read_text());assert data['passed']
        for p,h in data['sha256'].items():
            assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
    for src in (proof/'divider/overlay').glob('*.v'):
        assert src.read_bytes()==(out/'overlay'/src.name).read_bytes(),src
    paths=[Path(__file__).resolve(),out/'prepared.json',proof/'atomic/results.json',proof/'divider/results.json']+list((out/'overlay').glob('*.v'))+list(parent.glob('*.v'))
    (proof/'results.json').write_text(json.dumps(dict(passed=True,
        claim='Exact embedded atomic outputs/controls/reservation state proved inductively for arbitrary inputs, followed by complete divider sequential equivalence and arithmetic/cancel latency tests. Candidate overlay byte-identical to this proof composition. No added stages or altered instruction semantics.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS actual atomic/divider composition and exact divider latency',flush=True)
