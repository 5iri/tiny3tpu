#!/usr/bin/env python3
"""Maintain bank row-hit state alongside the current command, without delay."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent


def patch_bankmachine(evidence):
    import litedram.core.bankmachine as bankmachine
    import litedram.core.controller as controller
    original = Path(bankmachine.__file__).read_text()
    old = "        self.comb += row_hit.eq(row == slicer.row(cmd_buffer.source.addr))"
    new = '''        # Update the row comparison at the same edge as command/row state.
        # ACTIVATE opens the row of the held command; it cannot consume it.
        # Otherwise, an accepted replacement is compared with the held row.
        self.sync += If(row_open,
            row_hit.eq(1)
        ).Elif(cmd_buffer.sink.ready,
            row_hit.eq(row == slicer.row(cmd_buffer.sink.addr))
        )'''
    assert original.count(old)==1
    candidate = original.replace(old,new,1)
    # Avoid treating the unowned internal comparator as a public equivalence
    # point. Its value while the command buffer is empty is unobservable.
    candidate = candidate.replace("row_hit    = Signal()", 'row_hit    = Signal(name_override="row_hit_q")')
    exec(compile(candidate,str(Path(bankmachine.__file__)),"exec"),bankmachine.__dict__)
    controller.BankMachine = bankmachine.BankMachine
    out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
    (out/"bankmachine-original.py").write_text(original)
    (out/"bankmachine-candidate.py").write_text(candidate)
    paths=[Path(__file__),Path(bankmachine.__file__),out/"bankmachine-original.py",out/"bankmachine-candidate.py"]
    (out/"sources.json").write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+"\n")


if __name__=="__main__":
    import sys
    output=Path(sys.argv[sys.argv.index("--output-dir")+1])
    spec=importlib.util.spec_from_file_location("write_buffer",HERE.parent/"dram-write-buffer/generate.py")
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    base.patch_adapter(output/"write-buffer-evidence")
    patch_bankmachine(output/"row-hit-evidence")
    runpy.run_module("litedram.gen",run_name="__main__")
