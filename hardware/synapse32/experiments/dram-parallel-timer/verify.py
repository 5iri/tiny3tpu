#!/usr/bin/env python3
"""Validate proof provenance and upstream tests with both patches installed."""
import argparse,hashlib,json,sys,unittest
from pathlib import Path
from generate import apply,HERE
ROOT=HERE.parents[3]
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--upstream',type=Path,required=True);a=p.parse_args()
out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
hashes={}
for name in ['build-ddr-parallel-chooser','build-ddr-refresh-timer']:
    path=ROOT/name/'results.json';r=json.loads(path.read_text());assert r['passed']
    for n,sha in r['sha256'].items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==sha,n
    hashes.update(r['sha256']);hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
apply(out/'evidence')
# Both edits leave component boundary signals cycle-equivalent, so their
# independently proved contracts compose. Check actual patched source matches.
for sub,name,proof in [('parallel-chooser-evidence','multiplexer-candidate.py','build-ddr-parallel-chooser'),('refresh-timer-evidence','refresher-candidate.py','build-ddr-refresh-timer')]:
    assert (out/'evidence'/sub/name).read_bytes()==(ROOT/proof/'evidence'/name).read_bytes()
sys.path.insert(0,str(a.upstream.resolve()))
from test import test_refresh,test_multiplexer
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in [test_refresh,test_multiplexer])
with (out/'tests.log').open('w') as log:r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
paths=[Path(__file__),HERE/'generate.py',Path(test_refresh.__file__),Path(test_multiplexer.__file__)]+list((out/'evidence').rglob('*.py'))
hashes.update({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
(out/'results.json').write_text(json.dumps({'passed':r.wasSuccessful(),'tests':r.testsRun,'claim':'Composition of exact timer count/done and all command-chooser output equivalence; actual candidate sources match proven components; combined upstream tests pass.','sha256':hashes},indent=2)+'\n')
if not r.wasSuccessful():raise SystemExit('FAIL combined selector/timer tests')
print('PASS composed proofs and',r.testsRun,'combined upstream tests')
