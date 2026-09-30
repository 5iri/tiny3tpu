#!/usr/bin/env python3
"""Prove valid full-word capture equivalence, then test the native DDR adapter."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from generate import converter_classes, patch_adapter


def prove(out):
    from migen import Module, Signal
    from migen.fhdl import verilog
    original, candidate, classes = converter_classes()
    dut = Module()
    gold = classes[0](36, 576, 16, False)
    gate = classes[1](36, 576, 16, False)
    dut.submodules.gold = gold; dut.submodules.gate = gate
    valid = Signal(name="in_valid"); data = Signal(36, name="in_data")
    ready = Signal(name="out_ready"); first = Signal(name="in_first")
    same = Signal(name="same")
    for c in (gold, gate):
        dut.comb += [c.sink.valid.eq(valid), c.sink.data.eq(data), c.sink.first.eq(first),
                     c.sink.last.eq(0), c.source.ready.eq(ready)]
    checks = [gold.sink.ready == gate.sink.ready,
              gold.source.valid == gate.source.valid,
              gold.source.first == gate.source.first,
              gold.source.last == gate.source.last,
              gold.source.valid_token_count == gate.source.valid_token_count,
              gold.capture_index == gate.capture_index]
    for i in range(16):
        occupied = (gold.capture_index > i) | gold.source.valid
        checks.append(~occupied | (gold.source.data[i*36:(i+1)*36] == gate.source.data[i*36:(i+1)*36]))
    expr = checks[0]
    for check in checks[1:]: expr = expr & check
    dut.comb += same.eq(expr)
    (out / "capture-equiv.v").write_text(str(verilog.convert(dut, ios={valid, data, ready, first, same}, name="capture_equiv")))
    script = "read_verilog " + str(out / "capture-equiv.v") + "\n"
    script += "prep -top capture_equiv; flatten; opt; check -assert; sat -seq 3 -tempinduct -set-init-zero -prove same 1 -verify;\n"
    (out / "proof.ys").write_text(script)
    with (out / "proof.log").open("w") as log:
        subprocess.run(["/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys", "-Q", "-T", "-s", str(out / "proof.ys")], stdout=log, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    upstream = args.upstream.resolve()
    revision = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    assert revision == "7cc1e0f03d457230e9099b1635c9f9527499c0ca"
    prove(out)
    patch_adapter(out / "generation-evidence")
    sys.path.insert(0, str(upstream))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dram-command-buffer"))
    os.chdir(out)
    suite = unittest.defaultTestLoader.loadTestsFromName("test.test_adapter")
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName("width512_test"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    paths = [Path(__file__), Path(__file__).with_name("generate.py"), out / "capture-equiv.v", out / "proof.ys",
             upstream / "test/test_adapter.py", upstream / "test/common.py",
             Path(__file__).resolve().parent.parent / "dram-command-buffer/width512_test.py"]
    generation = json.loads((out / "generation-evidence/sources.json").read_text())
    paths += [Path(p) for p in generation]
    (out / "results.json").write_text(json.dumps({"revision": revision, "tests": result.testsRun,
        "native_write_deadline": True,
        "capture_equivalence": "temporal induction, full words, arbitrary valid/data/ready/reset",
        "passed": result.wasSuccessful(),
        "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
