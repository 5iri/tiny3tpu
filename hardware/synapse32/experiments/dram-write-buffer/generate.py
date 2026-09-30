#!/usr/bin/env python3
"""Break native DDR ready propagation with a two-entry wide write FIFO."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("write_capture", HERE.parent / "dram-write-capture/generate.py")
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)


def patch_adapter(evidence):
    import litedram.frontend.adapter as adapter
    out = Path(evidence); out.mkdir(parents=True, exist_ok=True)
    base.patch_adapter(out / "write-capture")
    source = (out / "write-capture/adapter-candidate.py").read_text()
    old = "wdata_buffer  = stream.SyncFIFO(port_to.wdata.description, 1)"
    assert source.count(old) == 1
    source = source.replace(old, "wdata_buffer  = stream.SyncFIFO(port_to.wdata.description, 2)")
    exec(compile(source, str(Path(adapter.__file__)), "exec"), adapter.__dict__)
    (out / "adapter-candidate.py").write_text(source)
    paths = [Path(__file__), out / "adapter-candidate.py"]
    paths += [Path(p) for p in json.loads((out / "write-capture/sources.json").read_text())]
    (out / "sources.json").write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, indent=2) + "\n")


if __name__ == "__main__":
    import sys
    output = Path(sys.argv[sys.argv.index("--output-dir") + 1])
    patch_adapter(output / "write-buffer-evidence")
    runpy.run_module("litedram.gen", run_name="__main__")
