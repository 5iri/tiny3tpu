#!/usr/bin/env python3
"""Compose cycle-equivalent bank selection and registered refresh terminal count."""
import importlib.util
from pathlib import Path
import runpy
HERE=Path(__file__).resolve().parent

def apply(evidence):
    for name,method,dest in [('dram-write-buffer','patch_adapter','write-buffer-evidence'),
                             ('dram-grant-onehot','patch_multiplexer','grant-onehot-evidence'),
                             ('dram-refresh-timer','patch_refresher','refresh-timer-evidence')]:
        spec=importlib.util.spec_from_file_location(name,HERE.parent/name/'generate.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        getattr(module,method)(Path(evidence)/dest)

if __name__=='__main__':
    import sys
    output=Path(sys.argv[sys.argv.index('--output-dir')+1])
    apply(output)
    runpy.run_module('litedram.gen',run_name='__main__')
