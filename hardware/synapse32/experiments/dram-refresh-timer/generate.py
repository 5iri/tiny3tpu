#!/usr/bin/env python3
"""Register refresh timer terminal count without changing its cycle."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
HERE=Path(__file__).resolve().parent


def patch_refresher(evidence):
    import litedram.core.refresher as refresher
    original=Path(refresher.__file__).read_text()
    start=original.index('class RefreshTimer(')
    end=original.index('class RefreshPostponer(',start)
    timer=original[start:end]
    old='''        self.sync += [
            If(self.wait & ~self.done,
                count.eq(count - 1)
            ).Else(
                count.eq(count.reset)
            )
        ]'''
    new='''        # Predict the zero flag at the same edge as the count update.
        # This preserves the exact refresh/ZQCS request cycle.
        self.sync += [
            If(self.wait & ~self.done,
                count.eq(count - 1),
                done.eq(count == 1)
            ).Else(
                count.eq(count.reset),
                done.eq(trefi == 1)
            )
        ]'''
    assert timer.count(old)==1
    timer=timer.replace(old,new).replace('done  = Signal()','done  = Signal(reset=(trefi == 1))')
    assert timer.count('            done.eq(count == 0),')==1
    timer=timer.replace('            done.eq(count == 0),\n','')
    candidate=original[:start]+timer+original[end:]
    exec(compile(candidate,str(Path(refresher.__file__)), 'exec'),refresher.__dict__)
    out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
    (out/'refresher-original.py').write_text(original)
    (out/'refresher-candidate.py').write_text(candidate)
    paths=[Path(__file__),Path(refresher.__file__),out/'refresher-original.py',out/'refresher-candidate.py']
    (out/'sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')


if __name__=='__main__':
    import sys
    output=Path(sys.argv[sys.argv.index('--output-dir')+1])
    spec=importlib.util.spec_from_file_location('write_buffer',HERE.parent/'dram-write-buffer/generate.py')
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    base.patch_adapter(output/'write-buffer-evidence')
    patch_refresher(output/'refresh-timer-evidence')
    runpy.run_module('litedram.gen',run_name='__main__')
