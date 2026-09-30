#!/usr/bin/env python3
"""Apply an isolated LiteDRAM command-buffer register, then run its generator."""
import hashlib
import json
from pathlib import Path
import runpy


def patch_adapter(evidence=None):
    import litedram.frontend.adapter as adapter
    source_path=Path(adapter.__file__)
    original=source_path.read_text()
    old='cmd_buffer       = stream.SyncFIFO([("sel", ratio), ("we", 1)], 0)'
    new='cmd_buffer       = stream.SyncFIFO([("sel", ratio), ("we", 1)], 1)'
    assert original.count(old)==1, "Unexpected LiteDRAM adapter version"
    patched=original.replace(old,new)
    # A buffered metadata enqueue is not write-data completion. The native
    # controller does not wait for wdata.valid after accepting a command.
    # Preserve the upstream ordering: finish assembling data, then issue CMD.
    old_commit='''            If(cmd_buffer.sink.ready,
                If(cmd_we,
                    NextState("CMD")'''
    new_commit='''            If(cmd_buffer.sink.ready,
                If(cmd_we,
                    NextState("WRITE-DRAIN")'''
    assert patched.count(old_commit)==1
    patched=patched.replace(old_commit,new_commit)
    marker="        self.comb += [\n            cmd_buffer.source.ready"
    drain='''        fsm.act("WRITE-DRAIN",
            If(wdata_finished,
                NextState("CMD")
            )
        )

'''
    assert patched.count(marker)==1
    patched=patched.replace(marker,drain+marker)
    # Change only this process. No installed package files are modified.
    exec(compile(patched,str(source_path),"exec"),adapter.__dict__)
    if evidence:
        target=Path(evidence);target.mkdir(parents=True,exist_ok=True)
        (target/"adapter_original.py").write_text(original)
        (target/"adapter_buffered.py").write_text(patched)
        (target/"adapter-sources.json").write_text(json.dumps({
            "installed_source":str(source_path),
            "original_sha256":hashlib.sha256(original.encode()).hexdigest(),
            "buffered_sha256":hashlib.sha256(patched.encode()).hexdigest()},indent=2)+'\n')
    return patched


if __name__=="__main__":
    import sys
    output=Path(sys.argv[sys.argv.index("--output-dir")+1])
    patch_adapter(output/"command-buffer-evidence")
    runpy.run_module("litedram.gen",run_name="__main__")
