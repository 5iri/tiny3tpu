#!/usr/bin/env python3
"""Use parallel masked selection for DDR bank commands."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
HERE=Path(__file__).resolve().parent


def patch_multiplexer(evidence):
    import litedram.core.multiplexer as multiplexer
    original=Path(multiplexer.__file__).read_text()
    start=original.index('class _CommandChooser(')
    end=original.index('# _Steerer',start)
    block=original[start:end]
    marker='        n = len(requests)'
    assert block.count(marker)==1
    block=block.replace(marker,marker+"\n        assert n > 0 and (n & (n-1)) == 0, 'Parallel chooser requires power-of-two banks'")
    block=block.replace('cmd.valid.eq(choices[arbiter.grant])',
        'cmd.valid.eq(reduce(or_, (valids[i] & (arbiter.grant == i) for i in range(n))))')
    old='getattr(cmd, name).eq(choices[arbiter.grant])'
    assert block.count(old)==2
    block=block.replace(old,
        'getattr(cmd, name).eq(reduce(or_, (choices[i] & Replicate(arbiter.grant == i, len(choices[i])) for i in range(n))))')
    block=block.replace('If(cmd.valid & cmd.ready & (arbiter.grant == i),',
        'If(valids[i] & cmd.ready & (arbiter.grant == i),')
    candidate=original[:start]+block+original[end:]
    exec(compile(candidate,str(Path(multiplexer.__file__)), 'exec'),multiplexer.__dict__)
    out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
    (out/'multiplexer-original.py').write_text(original)
    (out/'multiplexer-candidate.py').write_text(candidate)
    paths=[Path(__file__),Path(multiplexer.__file__),out/'multiplexer-original.py',out/'multiplexer-candidate.py']
    (out/'sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')


if __name__=='__main__':
    import sys
    output=Path(sys.argv[sys.argv.index('--output-dir')+1])
    spec=importlib.util.spec_from_file_location('write_buffer',HERE.parent/'dram-write-buffer/generate.py')
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    base.patch_adapter(output/'write-buffer-evidence')
    patch_multiplexer(output/'parallel-chooser-evidence')
    runpy.run_module('litedram.gen',run_name='__main__')
