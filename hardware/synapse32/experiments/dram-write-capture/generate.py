#!/usr/bin/env python3
"""Relax writes to an unfilled wide-word lane; preserve all valid output words."""
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent


def converter_classes():
    from litex.soc.interconnect import stream
    original = inspect.getsource(stream._UpConverter)
    old = "self.sync += If(load_part, Case(demux, cases))"
    assert original.count(old) == 1
    candidate = original.replace(old, "self.sync += If(sink.ready, Case(demux, cases))")
    classes = []
    for text in (original, candidate):
        # Export occupancy only for the proof harness; it has no hardware cost
        # unless explicitly connected. Data capture is the only functional edit.
        text = text.replace("        # Data path", "        self.capture_index = demux\n        # Data path", 1)
        namespace = dict(stream.__dict__)
        exec(compile(text, str(HERE / "generated_upconverter.py"), "exec"), namespace)
        classes.append(namespace["_UpConverter"])
    return original, candidate, classes


def patch_adapter(evidence=None):
    from litex.soc.interconnect import stream
    import litedram.frontend.adapter as adapter
    spec = importlib.util.spec_from_file_location("command_buffer", HERE.parent / "dram-command-buffer/generate.py")
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    source = base.patch_adapter(Path(evidence) / "command-buffer" if evidence else None)
    original, candidate, classes = converter_classes()

    def wide_write_converter(*args, **kwargs):
        # Limit the edit to the native upconverter's write datapath. In this
        # path every wide word accepts all ratio chunks, including zero-strobe
        # fillers. The adapter never asserts wdata_converter.sink.last.
        saved = stream._UpConverter
        try:
            stream._UpConverter = classes[1]
            return stream.StrideConverter(*args, **kwargs)
        finally:
            stream._UpConverter = saved

    old = "wdata_converter = stream.StrideConverter("
    before, after = source.split("class LiteDRAMNativePortUpConverter", 1)
    assert after.count(old) == 1
    source = before + "class LiteDRAMNativePortUpConverter" + after.replace(old, "wdata_converter = wide_write_converter(")
    adapter.__dict__["wide_write_converter"] = wide_write_converter
    exec(compile(source, str(Path(adapter.__file__)), "exec"), adapter.__dict__)
    if evidence:
        out = Path(evidence); out.mkdir(parents=True, exist_ok=True)
        (out / "upconverter-original.py").write_text(original)
        (out / "upconverter-candidate.py").write_text(candidate)
        (out / "adapter-candidate.py").write_text(source)
        paths = [HERE / "generate.py", HERE.parent / "dram-command-buffer/generate.py",
                 Path(stream.__file__), Path(adapter.__file__), *out.glob("*.py")]
        (out / "sources.json").write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, indent=2) + "\n")


if __name__ == "__main__":
    import sys
    output = Path(sys.argv[sys.argv.index("--output-dir") + 1])
    patch_adapter(output / "write-capture-evidence")
    runpy.run_module("litedram.gen", run_name="__main__")
