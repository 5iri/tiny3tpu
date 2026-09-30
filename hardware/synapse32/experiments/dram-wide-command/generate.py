#!/usr/bin/env python3
"""Queue completed wide native commands after the existing WRITE-DRAIN boundary."""
import hashlib,importlib.util,json,runpy
from pathlib import Path
HERE=Path(__file__).resolve().parent

def patch_adapter(evidence):
    import litedram.frontend.adapter as adapter
    out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('write_buffer',HERE.parent/'dram-write-buffer/generate.py')
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);base.patch_adapter(out/'write-buffer')
    original=(out/'write-buffer/adapter-candidate.py').read_text()
    start=original.index('class LiteDRAMNativePortUpConverter(')
    end=original.index('\nclass ',start+10)
    body=original[start:end]
    assert body.count('port_to.cmd')==5,body.count('port_to.cmd')
    body=body.replace('port_to.cmd','wide_cmd.sink')
    anchor='        ratio = port_to.data_width//port_from.data_width'
    assert body.count(anchor)==1
    body=body.replace(anchor,'''        wide_cmd = stream.SyncFIFO(port_to.cmd.description, 2)
        self.submodules += wide_cmd
        self.comb += wide_cmd.source.connect(port_to.cmd)

'''+anchor)
    candidate=original[:start]+body+original[end:]
    exec(compile(candidate,str(Path(adapter.__file__)),'exec'),adapter.__dict__)
    (out/'adapter-original.py').write_text(original);(out/'adapter-candidate.py').write_text(candidate)
    paths=[Path(__file__),out/'adapter-original.py',out/'adapter-candidate.py']
    paths += [Path(p) for p in json.loads((out/'write-buffer/sources.json').read_text())]
    (out/'sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')

if __name__=='__main__':
    import sys
    output=Path(sys.argv[sys.argv.index('--output-dir')+1])
    patch_adapter(output/'wide-command-evidence')
    runpy.run_module('litedram.gen',run_name='__main__')
