#!/usr/bin/env python3
"""Exercise the two-entry wide write FIFO under backpressure and dependencies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from generate import patch_adapter

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--upstream", type=Path, required=True)
args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
upstream = args.upstream.resolve()
revision = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
assert revision == "7cc1e0f03d457230e9099b1635c9f9527499c0ca"
patch_adapter(out / "generation-evidence")
sys.path.insert(0, str(upstream))
sys.path.insert(0, str(HERE.parent / "dram-command-buffer"))
os.chdir(out)
suite = unittest.defaultTestLoader.loadTestsFromName("test.test_adapter")
suite.addTests(unittest.defaultTestLoader.loadTestsFromName("width512_test"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
paths = [Path(__file__), HERE / "generate.py", upstream / "test/test_adapter.py", upstream / "test/common.py",
         HERE.parent / "dram-command-buffer/width512_test.py"]
paths += [Path(p) for p in json.loads((out / "generation-evidence/sources.json").read_text())]
(out / "results.json").write_text(json.dumps({"revision":revision, "tests":result.testsRun,
    "native_write_deadline":True,
    "passed":result.wasSuccessful(), "sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}, indent=2) + "\n")
raise SystemExit(0 if result.wasSuccessful() else 1)
