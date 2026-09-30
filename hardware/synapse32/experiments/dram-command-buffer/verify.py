#!/usr/bin/env python3
"""Run upstream width-converter tests against the installed and buffered adapter."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from generate import patch_adapter

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--upstream",type=Path,required=True)
parser.add_argument("--out",type=Path,required=True)
parser.add_argument("--buffered",action="store_true")
args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
upstream=args.upstream.resolve()
revision=subprocess.check_output(["git","-C",str(upstream),"rev-parse","HEAD"],text=True).strip()
assert revision=="7cc1e0f03d457230e9099b1635c9f9527499c0ca", "Tests must be LiteDRAM 2024.12"
if args.buffered:patch_adapter(out)
# Import the installed implementation before adding the upstream test directory.
import litedram.frontend.adapter
sys.path.insert(0,str(upstream))
os.chdir(out)
suite=unittest.defaultTestLoader.loadTestsFromName("test.test_adapter")
suite.addTests(unittest.defaultTestLoader.loadTestsFromName("width512_test"))
result=unittest.TextTestRunner(verbosity=2).run(suite)
paths=[upstream/"test/test_adapter.py",upstream/"test/common.py",Path(__file__),Path(__file__).with_name("generate.py"),Path(__file__).with_name("width512_test.py")]
(out/"results.json").write_text(json.dumps({"revision":revision,"buffered":args.buffered,
    "native_write_deadline":True,
    "tests":result.testsRun,"passed":result.wasSuccessful(),
    "sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
raise SystemExit(0 if result.wasSuccessful() else 1)
