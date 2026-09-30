#!/usr/bin/env python3
"""Cache the DDR chooser's one-hot grant on the original arbitration edge."""
import hashlib,importlib.util,inspect,json,runpy
from pathlib import Path
HERE=Path(__file__).resolve().parent

def patch_multiplexer(evidence):
    import litedram.core.multiplexer as multiplexer
    import migen.genlib.roundrobin as rr
    out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('parallel_chooser',HERE.parent/'dram-parallel-chooser/generate.py')
    parallel=importlib.util.module_from_spec(spec);spec.loader.exec_module(parallel)
    parallel.patch_multiplexer(out/'parallel-evidence')
    original=(out/'parallel-evidence/multiplexer-candidate.py').read_text()
    arbiter=inspect.getsource(rr.RoundRobin)
    assert arbiter.count('self.grant.eq(t)')==1
    decoded=arbiter.replace('class RoundRobin(', 'class _DecodedGrantRoundRobin(')
    marker='        self.grant = Signal(max=max(2, n))'
    assert decoded.count(marker)==1
    decoded=decoded.replace(marker,marker+'\n        self.grant_onehot = Signal(n, reset=1)')
    decoded=decoded.replace('self.grant.eq(t)', 'self.grant.eq(t), self.grant_onehot.eq(1 << t)')
    decoded=decoded.replace('self.comb += self.grant.eq(0)', 'self.comb += [self.grant.eq(0), self.grant_onehot.eq(1)]')
    candidate=original.replace('class _CommandChooser(',decoded+'\n\nclass _CommandChooser(',1)
    assert candidate.count('arbiter = RoundRobin(n, SP_CE)')==1
    candidate=candidate.replace('arbiter = RoundRobin(n, SP_CE)','arbiter = _DecodedGrantRoundRobin(n, SP_CE)')
    candidate=candidate.replace('arbiter.grant == i','arbiter.grant_onehot[i]')
    exec(compile(candidate,str(Path(multiplexer.__file__)),'exec'),multiplexer.__dict__)
    (out/'multiplexer-original.py').write_text((out/'parallel-evidence/multiplexer-original.py').read_text())
    (out/'multiplexer-candidate.py').write_text(candidate)
    (out/'roundrobin-original.py').write_text(arbiter)
    paths=[Path(__file__),Path(multiplexer.__file__),Path(rr.__file__),HERE.parent/'dram-parallel-chooser/generate.py',out/'multiplexer-original.py',out/'multiplexer-candidate.py',out/'roundrobin-original.py']
    (out/'sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')

if __name__=='__main__':
    import sys
    output=Path(sys.argv[sys.argv.index('--output-dir')+1])
    spec=importlib.util.spec_from_file_location('write_buffer',HERE.parent/'dram-write-buffer/generate.py')
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    base.patch_adapter(output/'write-buffer-evidence')
    patch_multiplexer(output/'grant-onehot-evidence')
    runpy.run_module('litedram.gen',run_name='__main__')
