#!/usr/bin/env python3
"""Check that native write data meets a scheduled controller phase."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--candidate", choices=("upstream","dram-command-buffer","dram-write-capture","dram-write-buffer"), required=True)
parser.add_argument("--upstream", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
import litedram.frontend.adapter
if args.candidate != "upstream":
    spec = importlib.util.spec_from_file_location("selected_adapter", HERE.parent / args.candidate / "generate.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.patch_adapter(out / "generation-evidence")
sys.path.insert(0,str(args.upstream.resolve())); os.chdir(out)
suite = unittest.defaultTestLoader.loadTestsFromName("width512_test.StrictNativeWriteTest")
result = unittest.TextTestRunner(verbosity=2).run(suite)
(out / "results.json").write_text(json.dumps({"candidate":args.candidate,"passed":result.wasSuccessful(),
    "native_write_deadline":True,"tests":result.testsRun},indent=2)+"\n")
raise SystemExit(0 if result.wasSuccessful() else 1)
